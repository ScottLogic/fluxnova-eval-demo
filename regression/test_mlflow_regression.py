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
import pandas as pd
import pytest
import requests
from fluxnova_mlflow_dataset import (
    ALL_DETERMINISTIC_SCORERS,
    BpmnLookup,
    MlflowTraceReader,
    TraceStoreError,
    decision_quality,
    evidence_citation,
    experiment_name_for,
    matches_golden,
)
from fluxnova_mlflow_dataset.goldens import load_goldens
from fluxnova_runner.agent_output import agent_final_output
from fluxnova_runner.agent_tool_calls import scorer_inputs_from_variables
from fluxnova_runner.client import Client
from fluxnova_runner.config import RunnerConfig
from fluxnova_runner.mock_workers import start_workers

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "fluxnova-runner" / "config" / "loan-assesment.yml"
_GOLDENS_PATH = _REPO_ROOT / "datasets" / "loan-assessment" / "goldens.json"

# Regression runs/assessments now deliberately share the same experiment as
# real/demo runs (rather than a separate "-regression" experiment) — this must
# be the literal target name, not run through experiment_name_for() again
# (which would double the "fluxnova-" prefix onto an already-prefixed name and
# silently create/target a different, empty experiment instead).
_REGRESSION_EXPERIMENT = experiment_name_for("loanAssessmentEvalProcess")

# Where the *raw agent traces* actually land. The OTel Collector always routes
# every trace (regardless of which MLflow experiment a caller's own client
# happens to be pointed at) to one fixed experiment, matching
# eval_trace_listener/eval-service-worker's shared default — see
# local-dev/.env's MLFLOW_EXPERIMENT_ID. Now the same experiment as
# _REGRESSION_EXPERIMENT above (see that constant's comment), but kept as its
# own name here since it's conceptually a different thing (raw traces vs. this
# suite's own Runs/dataset) — used to tag our own traces (see
# _tag_trace_as_regression) so eval-trace-listener can tell them apart from
# real/demo runs, which share this suite's exact same subprocess_id/agent_name.
_TRACE_EXPERIMENT_NAME = _REGRESSION_EXPERIMENT

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


def _is_yes(value: object) -> bool:
    return str(value).strip().lower() == "yes"


def _meets_evidence_citation_threshold(value: object) -> bool:
    return float(value) >= _EVIDENCE_CITATION_THRESHOLD


def _deterministic_passed(value: object) -> bool:
    """Pass rule for every deterministic scorer's value shape.

    Plain booleans (possibly surfaced as their string form, e.g. ``"true"``,
    depending on the store), or graded 0.0-1.0 scores (``tool_correctness`` and
    friends — treated as a hard gate here, requiring the full 1.0, since this is
    a regression *gate* not a benchmark).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) >= 1.0
    return str(value).strip().lower() in {"true", "yes", "1"}


# The LLM judges' pass rules. Unlike the deterministic scorers, a judge must
# always produce a verdict — a missing one means scoring errored (or, for
# matches_golden, that the golden lacks an expected_output). Gate on the
# verdicts rather than `result.passed`: that also inspects the expected_output
# expectation column, whose value is free text rather than a yes/no rating.
_JUDGE_PASS_RULES = {
    decision_quality.name: _is_yes,
    # matches_golden thresholds at GOLDEN_MATCH_THRESHOLD inside the scorer and
    # returns a "yes"/"no" verdict, keeping the raw score in its metadata.
    matches_golden.name: _is_yes,
    evidence_citation.name: _meets_evidence_citation_threshold,
}

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
    except TraceStoreError as exc:
        _log.warning("Could not tag instance %s's trace as regression: %s", instance_id, exc)


def _run_agent(client: Client, cfg: RunnerConfig, variables: dict) -> tuple[str, dict]:
    """Drive one live agent run and return its final output plus raw process variables.

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
    return final_output, run_variables


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and value != value)  # NaN != itself


def _jsonable(value: object) -> object:
    """Coerce one ``eval_results`` cell to plain JSON (numpy scalars, NaN -> None)."""
    if _is_missing(value):
        return None
    if hasattr(value, "item"):
        value = value.item()  # numpy scalar -> Python
    return value if isinstance(value, (bool, int, float, str)) else str(value)


def _scorer_results(row: pd.Series) -> list[dict]:
    """One ``{name, status, value, rationale}`` entry per gating scorer for one golden.

    ``status`` is ``"passed"``, ``"failed"`` or ``"n/a"`` — the last for a
    deterministic scorer that reports "not applicable" (``None``) for this
    golden's profile, e.g. ``no_collateral_check_when_no_collateral`` when the
    applicant has collateral. A scorer that errored, or a judge that produced no
    verdict, is a failure.
    """
    results = []
    for scorer in _GATING_SCORERS:
        name = scorer.name
        value = row.get(f"{name}/value")
        rationale = _jsonable(row.get(f"{name}/rationale"))
        error = _jsonable(row.get(f"{name}/error_message"))
        if not _is_missing(value):
            passes = _JUDGE_PASS_RULES.get(name, _deterministic_passed)
            status = "passed" if passes(value) else "failed"
        elif error:
            status, rationale = "failed", f"Scorer errored: {error}"
        elif name in _JUDGE_PASS_RULES:
            status, rationale = "failed", "Judge produced no verdict"
        else:
            status = "n/a"
        results.append(
            {"name": name, "status": status, "value": _jsonable(value), "rationale": rationale}
        )
    return results


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
    output, run_variables = _run_agent(loan_agent, cfg, variables)
    _log.info(
        "Ran live agent in %.1fs (%d chars of output)", time.perf_counter() - started, len(output)
    )

    row = {
        "inputs": scorer_inputs_from_variables(variables, run_variables, tool_names),
        "outputs": output,
        "expectations": {"expected_output": golden["expected_output"]},
    }
    _log.info("Scoring with %d scorers...", len(_GATING_SCORERS))
    result = mlflow.genai.evaluate(data=[row], scorers=_GATING_SCORERS)

    scorer_results = _scorer_results(result.tables["eval_results"].iloc[0])
    json_metadata["scorers"] = scorer_results
    failed = [entry for entry in scorer_results if entry["status"] == "failed"]
    assert not failed, f"{len(failed)}/{len(scorer_results)} scorer(s) failed:\n" + "\n".join(
        f"  - {entry['name']} = {entry['value']!r}: {entry['rationale']}" for entry in failed
    )
