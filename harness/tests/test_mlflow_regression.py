"""MLflow *agent* regression test (see
https://mlflow.org/docs/latest/genai/eval-monitor/regression-testing/) for the
Fluxnova loan-assessment agent.

Unlike ``mlflow_eval``'s offline batch evaluation (which measures aggregate
scores across every *recorded* run) or ``deep_eval`` (DEPRECATED), this is a
gating check that actually runs the live agent: for every scenario in the
golden dataset (``datasets/loan-assessment/goldens.json``) it drives the agent
end-to-end via ``fluxnova-runner`` and asserts the agent's *actual* output
still satisfies the shared ``decision_quality`` guideline judge (see
``fluxnova_mlflow_dataset.scorers``). This matches MLflow's canonical
regression-testing pattern — a ``predict_fn`` that invokes the real agent per
row — rather than merely re-scoring the golden's own reference answer.

Each golden is turned into a set of process variables (see
:func:`_golden_to_variables`): the applicant-facing ``input_variables`` the BPMN
is started with, plus one ``_mock_output_<key>`` variable per value in the
golden's ``tool_responses`` so a single shared mock-worker pool replays that
scenario's tool results (see ``fluxnova_runner.mock_workers``). The agent's
final output is then read back from its MLflow trace, exactly as the
eval-service-worker does (``eval_service_worker.scoring``).

Results are recorded to the same shared PostgreSQL-backed MLflow tracking store
used by the rest of the project (see ``local-dev/postgres-up.sh``), under a
dedicated ``fluxnova-loanAssessmentProcess-regression`` experiment so runs
don't mix with real recorded agent runs.

Prerequisites (the full live stack must be up): the Fluxnova engine, the shared
Postgres store, the OTel collector, MLflow, and Ollama. The test skips cleanly
if the engine or tracking store isn't reachable.

Run with:
    pytest harness/tests/test_mlflow_regression.py -v
"""

from __future__ import annotations

import os
from pathlib import Path

import mlflow
import pytest
import requests
from fluxnova_mlflow_dataset import (
    MlflowTraceReader,
    decision_quality,
    default_tracking_uri,
    experiment_name_for,
)
from fluxnova_mlflow_dataset.goldens import load_goldens
from fluxnova_runner.client import Client
from fluxnova_runner.config import RunnerConfig
from fluxnova_runner.mock_workers import start_workers

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _REPO_ROOT / "config" / "loan-assesment.yml"
_GOLDENS_PATH = _REPO_ROOT / "datasets" / "loan-assessment" / "goldens.json"

# Regression runs/assessments are logged under a dedicated experiment (not the
# live "fluxnova-loanAssessmentProcess" experiment the OTel collector exports
# real agent traces into) so they don't clutter it.
_REGRESSION_EXPERIMENT = experiment_name_for("loanAssessmentProcess-regression")

# How long to allow one golden's full agentic subprocess run to finish, then how
# long to wait for its trace to land in MLflow (the OTel collector exports spans
# asynchronously, a few seconds after the subprocess ends). Overridable via env.
# A single llama3.2-driven agent run takes several minutes, so the activity
# timeout is generous by default.
_ACTIVITY_TIMEOUT = float(os.environ.get("REGRESSION_ACTIVITY_TIMEOUT", "600"))
_TRACE_TIMEOUT = float(os.environ.get("REGRESSION_TRACE_TIMEOUT", "60"))

# Matches fluxnova_runner.mock_workers._MOCK_VAR_PREFIX — the namespace under
# which each golden's tool_responses are fed to the shared mock-worker pool.
_MOCK_PREFIX = "_mock_output_"


def _golden_to_variables(cfg: RunnerConfig, golden: dict) -> dict:
    """Turn one golden into the process variables that reproduce its scenario.

    Starts from the config's base variables (applicationId/customerId/etc.),
    overrides the applicant-facing inputs from the golden's ``input_variables``,
    then adds one ``_mock_output_<key>`` variable per value in the golden's
    ``tool_responses`` so the shared mock workers return this scenario's tool
    results instead of the config defaults.
    """
    variables: dict = {**cfg.variables, **golden["input_variables"]}
    for outputs in golden["tool_responses"].values():
        for key, value in outputs.items():
            variables[f"{_MOCK_PREFIX}{key}"] = value
    return variables


def _engine_reachable(cfg: RunnerConfig) -> bool:
    try:
        return requests.get(f"{cfg.fluxnova_url}/version", timeout=3).ok
    except requests.RequestException:
        return False


@mlflow.test
def test_agent_reproduces_golden_decisions() -> None:
    """Run the real loan-assessment agent on each golden scenario and assert its
    *actual* output still satisfies the ``decision_quality`` guidelines.

    The ``predict_fn`` drives the live agent per golden: start a process instance
    with that scenario's variables, wait for the agentic subprocess to finish,
    then read the agent's actual final output back from its MLflow trace.
    """
    cfg = RunnerConfig.from_file(_CONFIG_PATH)
    if not _engine_reachable(cfg):
        pytest.skip(
            f"Fluxnova engine not reachable at {cfg.fluxnova_url} — start the live stack"
        )
    assert cfg.subprocess_id, (
        "config is missing subprocess_id (the agent ad-hoc subprocess element id)"
    )

    tracking_uri = default_tracking_uri(_REPO_ROOT)
    mlflow.set_tracking_uri(tracking_uri)
    try:
        # The collector exports real agent traces into the live process
        # experiment; the reader must search there, not the regression one.
        live_experiment = mlflow.set_experiment(experiment_name_for(cfg.process_key))
    except Exception as exc:  # noqa: BLE001 - any connect/store failure => skip
        pytest.skip(f"MLflow tracking store not reachable at {tracking_uri}: {exc}")

    reader = MlflowTraceReader(tracking_uri, live_experiment.experiment_id)
    client = Client(
        base_url=cfg.fluxnova_url,
        username=os.environ.get("FLUXNOVA_USERNAME"),
        password=os.environ.get("FLUXNOVA_PASSWORD"),
    )

    # Deploy the BPMN once and start a single long-lived mock-worker pool; each
    # golden run then rides its own tool results in via _mock_output_* variables.
    client.deploy(cfg.bpmn_path, deployment_name=cfg.deployment_name)
    start_workers(
        cfg,
        username=os.environ.get("FLUXNOVA_USERNAME"),
        password=os.environ.get("FLUXNOVA_PASSWORD"),
    )

    # Log this test's evaluation run under the dedicated regression experiment.
    mlflow.set_experiment(_REGRESSION_EXPERIMENT)

    goldens = load_goldens(_GOLDENS_PATH)
    assert goldens, f"No goldens found at {_GOLDENS_PATH}"

    def predict_fn(*, variables: dict) -> str:
        instance_id = client.start_process(cfg.process_key, variables)
        client.wait_for_activity_completion(
            instance_id, cfg.subprocess_id, timeout=_ACTIVITY_TIMEOUT
        )
        reader.wait_for_trace(instance_id, timeout=_TRACE_TIMEOUT)
        final_output = reader.get_final_output(instance_id)
        assert final_output, f"No agent final output found for instance {instance_id}"
        return final_output

    data = [
        {
            "inputs": {"variables": _golden_to_variables(cfg, golden)},
            "expectations": {"expected_output": golden["expected_output"]},
        }
        for golden in goldens
    ]

    # MLflow otherwise runs predict_fn on the first row up-front to validate it,
    # which would drive one extra (several-minute) agent run before the real
    # evaluation loop — skip it since predict_fn is exercised by the loop anyway.
    os.environ.setdefault("MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION", "True")

    result = mlflow.genai.evaluate(
        data=data, predict_fn=predict_fn, scorers=[decision_quality]
    )
    assert result.passed, result.reason
