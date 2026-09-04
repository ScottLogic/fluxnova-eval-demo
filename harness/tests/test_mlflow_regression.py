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
final output is read back from the run's ``_agentConversationHistory`` process
variable (see ``fluxnova_runner.agent_output``) — deliberately *not* from the
MLflow trace, since a nested ``mlflow.search_traces`` inside a ``predict_fn``
corrupts MLflow's active-trace context and breaks assessment logging.

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
    decision_quality,
    experiment_name_for,
)
from fluxnova_mlflow_dataset.goldens import load_goldens
from fluxnova_runner.agent_output import agent_final_output
from fluxnova_runner.client import Client
from fluxnova_runner.config import RunnerConfig
from fluxnova_runner.mock_workers import start_workers

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _REPO_ROOT / "config" / "loan-assesment.yml"
_GOLDENS_PATH = _REPO_ROOT / "datasets" / "loan-assessment" / "goldens.json"

# Regression runs/assessments are logged under a dedicated experiment so they don't clutter it.
_REGRESSION_EXPERIMENT = experiment_name_for("loanAssessmentProcess-regression")

# How long to allow one golden's full agentic subprocess run to finish before
# giving up. Overridable via env.
_ACTIVITY_TIMEOUT = float(os.environ.get("REGRESSION_ACTIVITY_TIMEOUT", "600"))

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


def _run_agent(client: Client, cfg: RunnerConfig, variables: dict) -> str:
    """Drive one live agent run and return its actual final output.

    Starts a process instance, waits for the agentic subprocess to finish, then
    reads the agent's final response back from the run's process variables
    (``_agentConversationHistory``) — deliberately not from the MLflow trace, so
    no ``mlflow.*`` call happens here (see ``fluxnova_runner.agent_output``).
    """
    instance_id = client.start_process(cfg.process_key, variables)
    client.wait_for_activity_completion(
        instance_id, cfg.subprocess_id, timeout=_ACTIVITY_TIMEOUT
    )
    final_output = agent_final_output(client.get_variables(instance_id))
    assert final_output, f"No agent final output found for instance {instance_id}"
    return final_output


@pytest.fixture(scope="session")
def cfg() -> RunnerConfig:
    """Load the runner config once; skip the whole suite if the engine is down."""
    config = RunnerConfig.from_file(_CONFIG_PATH)
    if not _engine_reachable(config):
        pytest.skip(
            f"Fluxnova engine not reachable at {config.fluxnova_url} — start the live stack"
        )
    assert config.subprocess_id, (
        "config is missing subprocess_id (the agent ad-hoc subprocess element id)"
    )
    return config


@pytest.fixture(scope="session")
def regression_experiment() -> str:
    """Verify the MLflow tracking store is reachable and select the experiment.

    ``tests/conftest.py`` already pointed ``MLFLOW_TRACKING_URI`` /
    ``MLFLOW_EXPERIMENT_NAME`` at the shared Postgres store + regression
    experiment *before* ``@mlflow.test`` opens this run (setting them only inside
    the test body would be too late — the run would open in the ambient local
    store and get orphaned). This fixture just re-asserts the experiment as a
    reachability probe so an unreachable store skips cleanly rather than erroring
    deep inside ``evaluate()``.
    """
    try:
        mlflow.set_experiment(_REGRESSION_EXPERIMENT)
    except Exception as exc:  # noqa: BLE001 - any connect/store failure => skip
        pytest.skip(
            f"MLflow tracking store not reachable at {mlflow.get_tracking_uri()}: {exc}"
        )
    return _REGRESSION_EXPERIMENT


@pytest.fixture(scope="session")
def loan_agent(cfg: RunnerConfig, regression_experiment: str) -> Client:
    """Deploy the BPMN once and start a single long-lived mock-worker pool.

    The pool is shared across every golden; each run rides its own tool results
    in via ``_mock_output_*`` variables (see :func:`_golden_to_variables`).
    Depends on ``regression_experiment`` so we don't do this expensive live
    setup if results couldn't be logged anyway.
    """
    client = Client(
        base_url=cfg.fluxnova_url,
        username=os.environ.get("FLUXNOVA_USERNAME"),
        password=os.environ.get("FLUXNOVA_PASSWORD"),
    )
    client.deploy(cfg.bpmn_path, deployment_name=cfg.deployment_name)
    start_workers(
        cfg,
        username=os.environ.get("FLUXNOVA_USERNAME"),
        password=os.environ.get("FLUXNOVA_PASSWORD"),
    )
    return client


@pytest.fixture(scope="session")
def evaluation_data(cfg: RunnerConfig, loan_agent: Client) -> list[dict]:
    """Phase 1 — run the live agent on every golden and collect its real output.

    All agent runs (and therefore all live agent tracing) happen here, up-front
    during fixture setup, *before* any scoring. The test then scores these static
    ``outputs``, so ``evaluate`` never invokes a ``predict_fn`` — which would
    otherwise wrap each live call in its own MLflow trace that collides with the
    out-of-process agent's OTel trace and breaks assessment logging
    (``'NoneType' object has no attribute 'info'``).
    """
    goldens = load_goldens(_GOLDENS_PATH)
    assert goldens, f"No goldens found at {_GOLDENS_PATH}"

    data: list[dict] = []
    for golden in goldens:
        variables = _golden_to_variables(cfg, golden)
        data.append(
            {
                "inputs": {"variables": variables},
                "outputs": _run_agent(loan_agent, cfg, variables),
                "expectations": {"expected_output": golden["expected_output"]},
            }
        )
    return data


@mlflow.test
def test_agent_reproduces_golden_decisions(evaluation_data: list[dict]) -> None:
    """Assert the loan-assessment agent's *actual* output on every golden still
    satisfies the shared ``decision_quality`` guideline judge.

    This is MLflow's regression-testing pattern adapted for an out-of-process
    agent: the live agent is driven per golden (in the ``evaluation_data``
    fixture) and its real output scored here — rather than merely re-scoring the
    golden's own reference answer. ``@mlflow.test`` tags this as a regression
    test run (run type ``test`` + a session id) and records its pass/fail status.
    """
    result = mlflow.genai.evaluate(data=evaluation_data, scorers=[decision_quality])

    # Guard against every scorer silently erroring (which leaves zero recorded
    # assessments and makes result.passed default to truthy): require a real
    # decision_quality verdict for every row before trusting the pass/fail.
    verdicts = result.tables["eval_results"]["decision_quality/value"]
    assert verdicts.notna().all(), (
        "decision_quality did not produce a verdict for every golden — scoring "
        f"errored. Verdicts: {verdicts.tolist()}"
    )
    assert result.passed, result.reason
