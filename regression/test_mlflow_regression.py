"""MLflow *agent* regression test for the Fluxnova loan-assessment agent.

This is a gating check that runs the live agent.
There is one test per scenario in the golden dataset: each runs the agent end-to-end
via `fluxnova-runner` once, then scores that one output with every gating scorer in a
single `mlflow.genai.evaluate()` call and asserts they all pass.

Prerequisites (the full live stack must be up): the Fluxnova engine, the shared
Postgres store, the OTel collector and MLflow. The test skips cleanly
if the engine or tracking store isn't reachable.

Run with:
    pytest regression/test_mlflow_regression.py -v
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import mlflow
import pytest
import requests
from fluxnova_mlflow_dataset import (
    ALL_DETERMINISTIC_SCORERS,
    BpmnLookup,
    MlflowTraceReader,
    decision_quality,
    evidence_citation,
    experiment_name_for,
    matches_golden,
)
from fluxnova_mlflow_dataset.experiments import require_remote_artifacts
from fluxnova_mlflow_dataset.goldens import load_goldens
from fluxnova_mlflow_dataset.scorers import DECISION_QUALITY_RUBRIC_VERSION
from fluxnova_runner.agent_output import agent_final_output
from fluxnova_runner.agent_tool_calls import scorer_inputs_from_variables
from fluxnova_runner.client import Client
from fluxnova_runner.config import RunnerConfig
from fluxnova_runner.mock_workers import start_workers

from regression.reporting import build_report, failure_message, write_report

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "fluxnova-runner" / "config" / "loan-assesment.yml"
_GOLDENS_PATH = _REPO_ROOT / "datasets" / "loan-assessment" / "goldens.json"

# Match conftest/plugin selection, respecting an explicit regression override.
# Raw agent traces always follow the collector's independently configured target.
_TRACE_EXPERIMENT_NAME = os.environ.get(
    "EVAL_SERVICE_EXPERIMENT_NAME", experiment_name_for("loanAssessmentEvalProcess")
)
_REGRESSION_EXPERIMENT = os.environ.get("MLFLOW_EXPERIMENT_NAME", _TRACE_EXPERIMENT_NAME)

# Tag written onto every trace this suite generates — must match
# eval_trace_listener.listener._REGRESSION_TAG_NAME/_REGRESSION_TAG_VALUE.
_REGRESSION_TAG_NAME = "source"
_REGRESSION_TAG_VALUE = "regression"

# How long to allow one golden's full agentic subprocess run to finish before
# giving up. Overridable via env.
_ACTIVITY_TIMEOUT = float(os.environ.get("REGRESSION_ACTIVITY_TIMEOUT", "600"))

# Matches fluxnova_runner.mock_workers._MOCK_VAR_PREFIX — the namespace under
# which each golden's tool_responses are fed to the shared mock-worker pool.
_MOCK_PREFIX = "_mock_output_"

# Minimum `evidence_citation` judge score (0.0–1.0) counted as a pass for the
# gating test. Overridable via env so CI can tune the bar without a code change,
# mirroring REGRESSION_GOLDEN_MATCH_THRESHOLD.
_EVIDENCE_CITATION_THRESHOLD = float(
    os.environ.get("REGRESSION_EVIDENCE_CITATION_THRESHOLD", "0.7")
)

_log = logging.getLogger("fluxnova.regression")

# Loaded at collection time so each golden becomes its own parametrized test
# (and so `pytest -k <scenario>` drives just that one golden through the agent).
_GOLDENS = load_goldens(_GOLDENS_PATH)


_GATING_SCORERS = [decision_quality, matches_golden, evidence_citation, *ALL_DETERMINISTIC_SCORERS]


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


def _scenario_id(golden: dict) -> str | None:
    """The golden's scenario name as its test id (``None`` lets pytest auto-number it)."""
    return (golden.get("additional_metadata") or {}).get("scenario")


def _tag_trace_as_regression(instance_id: str) -> None:
    """Best-effort: tag this run's MLflow trace so eval-trace-listener skips it.

    Regression runs share the exact same ``subprocess_id`` (and therefore the
    same ``gen_ai.agent.name``) as real/demo runs, so the listener's
    ``agent_names`` filter alone can't tell them apart — see
    ``eval_trace_listener.listener``'s ``_is_regression_trace``. Tagging is
    genuinely best-effort (the OTel Collector delivers spans asynchronously, and
    this suite otherwise deliberately avoids MLflow calls around the live run —
    see ``_run_agent``'s docstring): a failure here must never fail the test
    itself, just risk the listener scoring this one run as if it were real.
    """
    try:
        experiment = mlflow.get_experiment_by_name(_TRACE_EXPERIMENT_NAME)
        if experiment is None:
            _log.warning(
                "Trace experiment %r not found — can't tag instance %s as regression",
                _TRACE_EXPERIMENT_NAME,
                instance_id,
            )
            return
        reader = MlflowTraceReader(mlflow.get_tracking_uri(), experiment.experiment_id)
        trace = reader.wait_for_trace(instance_id, timeout=30.0, poll_interval=3.0)
        mlflow.MlflowClient().set_trace_tag(
            trace.info.trace_id, _REGRESSION_TAG_NAME, _REGRESSION_TAG_VALUE
        )
    except Exception as exc:  # noqa: BLE001 - tagging must not discard captured results
        _log.warning("Could not tag instance %s's trace as regression: %s", instance_id, exc)


def _run_agent(client: Client, cfg: RunnerConfig, variables: dict) -> tuple[str, dict, str]:
    """Drive one live agent run and return output, raw variables and process ID.

    Starts a process instance, waits for the agentic subprocess to finish, then
    reads the run's process variables back — deliberately not from the MLflow
    trace (the agent's actual output comes from Fluxnova, not MLflow). The one
    exception is ``_tag_trace_as_regression`` at the end: a fire-and-forget,
    best-effort tag write that never affects — and can't fail — the returned
    output/variables above.
    """
    instance_id = client.start_process(cfg.process_key, variables)
    client.wait_for_activity_completion(
        instance_id, cfg.subprocess_id, timeout=_ACTIVITY_TIMEOUT
    )
    run_variables = client.get_variables(instance_id)
    final_output = agent_final_output(run_variables)
    assert final_output, f"No agent final output found for instance {instance_id}"
    _tag_trace_as_regression(instance_id)
    return final_output, run_variables, instance_id


def _report_gate(result, rows: list[dict], names: list[str], gate: str,
                 thresholds=None, *, scenario: str | None = None, assert_passed=True) -> dict:
    """Persist replayable evidence before asserting; never overwrite another scenario."""
    report = build_report(result.tables["eval_results"], rows, names, gate, thresholds)
    report.update(run_id=result.run_id, decision_quality_model=decision_quality.model,
                  decision_quality_rubric_version=DECISION_QUALITY_RUBRIC_VERSION)
    root = Path(os.environ.get("REGRESSION_REPORT_DIR", str(_REPO_ROOT / "local-dev/.mlflow/reports")))
    relative = Path(scenario) / f"{gate}.json" if scenario else Path(f"{gate}.json")
    path = root / result.run_id / relative
    write_report(report, path)
    mlflow.log_dict(report, f"regression/{relative.as_posix()}", run_id=result.run_id)
    _log.info("%s: %d scenarios; report %s", gate, len(report["cases"]), path)
    if assert_passed:
        assert not report["failures"], failure_message(report)
    return report


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
    """Verify the MLflow tracking server is reachable and select the experiment.

    ``conftest.py`` already pointed ``MLFLOW_TRACKING_URI`` /
    ``MLFLOW_EXPERIMENT_NAME`` at the shared MLflow tracking *server* (HTTP) +
    regression experiment *before* ``@mlflow.test`` opens this run (setting them
    only inside the test body would be too late — the run would open in the
    ambient local store and get orphaned). Going through the server (rather than
    Postgres directly) also sidesteps MLflow's strict client-side schema-version
    check, so a server/client version drift no longer makes this skip. This
    fixture just re-asserts the experiment as a reachability probe so an
    unreachable server skips cleanly rather than erroring deep inside
    ``evaluate()``.
    """
    try:
        experiment = mlflow.set_experiment(_REGRESSION_EXPERIMENT)
    except Exception as exc:  # noqa: BLE001 - any connect/store failure => skip
        pytest.skip(
            f"MLflow tracking store not reachable at {mlflow.get_tracking_uri()}: {exc}"
        )
    require_remote_artifacts(experiment)
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
def tool_names(cfg: RunnerConfig) -> dict[str, str | None]:
    """``{BPMN service task element id: display name}``, read once from the BPMN.

    The agent's tool-call history (``_agentConversationHistory``) records each
    call's BPMN element id (``ServiceTask_...``), but the scorers key on the
    human-readable display name — see
    ``fluxnova_runner.agent_tool_calls.tool_calls_from_variables``.
    """
    return BpmnLookup(cfg.bpmn_path, cfg.subprocess_id).tool_names()


########################## Regression tests ##########################

@mlflow.test
@pytest.mark.parametrize("golden", _GOLDENS, ids=_scenario_id)
def test_agent_passes_golden(
    golden: dict, cfg: RunnerConfig, loan_agent: Client, tool_names: dict, json_metadata: dict
) -> None:
    """Drive one golden through the live agent and assert every gating scorer passes.

    The agent runs exactly once per golden, and that one output is scored by
    every scorer in a single ``evaluate()`` call, so every scorer judges the
    same real (non-deterministic) output:

    - ``decision_quality`` — guideline judge: a definitive APPROVE/REJECT backed
      by specific cited evidence.
    - ``matches_golden`` — judge: same decision and evidence categories as the
      golden's ``expected_output``.
    - ``evidence_citation`` — graded judge, thresholded at
      ``REGRESSION_EVIDENCE_CITATION_THRESHOLD``.
    - ``ALL_DETERMINISTIC_SCORERS`` — code checks on the run's tool calls,
      ordering, arguments and iteration count, graded from the process
      variables (see ``fluxnova_runner.agent_tool_calls``) — no MLflow trace needed.

    Every scorer's result is recorded in the JSON report's per-test
    ``metadata.scorers`` (read by ``ui_api.regression_runner``), and the
    assertion lists every failing scorer rather than stopping at the first.
    """
    variables = _golden_to_variables(cfg, golden)
    started = time.perf_counter()
    output, run_variables, instance_id = _run_agent(loan_agent, cfg, variables)
    _log.info(
        "Ran live agent in %.1fs (%d chars of output)", time.perf_counter() - started, len(output)
    )

    row = {
        "inputs": {**scorer_inputs_from_variables(variables, run_variables, tool_names),
                   "scenario": _scenario_id(golden), "process_instance_id": instance_id},
        "outputs": output,
        "expectations": {"expected_output": golden["expected_output"]},
    }
    _log.info("Scoring with %d scorers...", len(_GATING_SCORERS))
    result = mlflow.genai.evaluate(data=[row], scorers=_GATING_SCORERS)

    reports = []
    for gate, names, thresholds in [
        ("decision_quality", [decision_quality.name], None),
        ("matches_golden", [matches_golden.name], None),
        ("evidence_citation", [evidence_citation.name], {evidence_citation.name: _EVIDENCE_CITATION_THRESHOLD}),
        ("deterministic", [s.name for s in ALL_DETERMINISTIC_SCORERS], None),
    ]:
        reports.append(_report_gate(result, [row], names, gate, thresholds,
                                    scenario=_scenario_id(golden), assert_passed=False))
    json_metadata["scorers"] = [
        {"name": name, "status": "n/a" if assessment["status"] == "not_applicable" else assessment["status"],
         "value": assessment["value"], "rationale": assessment["error"] or assessment["rationale"]}
        for report in reports for name, assessment in report["cases"][0]["scorers"].items()
    ]
    json_metadata["process_instance_id"] = instance_id
    assert not any(report["failures"] for report in reports), "\n".join(
        failure_message(report) for report in reports if report["failures"]
    )
