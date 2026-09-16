"""MLflow *agent* regression test for the Fluxnova loan-assessment agent.

This is a gating check that runs the live agent.
For every scenario in the golden dataset it runs the agent end-to-end via `fluxnova-runner`
and asserts the agent's output passes the specified tests.
This follows MLflow's canonical regression-testing pattern.

Prerequisites (the full live stack must be up): the Fluxnova engine, the shared
Postgres store, the OTel collector and MLflow. The test skips cleanly
if the engine or tracking store isn't reachable.

Run with:
    pytest regression/test_mlflow_regression.py -v
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import mlflow
import pytest
import requests
from fluxnova_mlflow_dataset import (
    ALL_DETERMINISTIC_SCORERS,
    GOLDEN_MATCH_THRESHOLD,
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


def _cache_key(variables: dict) -> str:
    """A stable key for one scenario's process variables, for ``predict_fn``'s cache."""
    return json.dumps(variables, sort_keys=True, default=str)


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


@pytest.fixture(scope="session")
def _run_cache() -> dict[str, dict]:
    """Session-wide cache: scenario key -> ``{"output", "scorer_inputs"}``.

    Populated by ``predict_fn`` the first time each scenario is requested (by
    ``evaluation_rows``, eagerly, before any ``evaluate()`` call), then just
    replayed for every subsequent call — see ``predict_fn``'s docstring.
    """
    return {}


@pytest.fixture(scope="session")
def predict_fn(cfg: RunnerConfig, loan_agent: Client, tool_names: dict, _run_cache: dict):
    """Build the MLflow ``predict_fn``: drives one live agent run per distinct
    ``input_variables`` and caches its result.

    ``mlflow.genai.evaluate()`` calls this once per row for *every* test's own
    ``evaluate()`` call below. Without caching, a scenario already scored by
    ``test_agent_reaches_evidence_backed_decision`` would be driven through the
    live (and not fully deterministic) agent again for
    ``test_agent_matches_golden_decisions``, risking a different actual output
    per scorer. Caching keeps one real run per scenario, replayed for every
    gate — and lets ``evaluation_rows`` read back the same run's tool-call
    data to build each row's full scorer ``inputs``.
    """

    def _predict(input_variables: dict, **_scorer_only_fields: object) -> str:
        # `mlflow.genai.evaluate()` calls `predict_fn(**row["inputs"])` — and once
        # a row's `inputs` also carries `tool_calls`/`iterations` (for the
        # deterministic scorers), those arrive here as extra kwargs this
        # function has no use for (it only needs `input_variables` to start the
        # run) — accept and ignore them rather than raising `TypeError`.
        cache_key = _cache_key(input_variables)
        cached = _run_cache.get(cache_key)
        if cached is not None:
            return cached["output"]
        started = time.perf_counter()
        output, run_variables = _run_agent(loan_agent, cfg, input_variables)
        elapsed = time.perf_counter() - started
        _log.info("Ran live agent scenario in %.1fs (%d chars of output)", elapsed, len(output))
        _run_cache[cache_key] = {
            "output": output,
            "scorer_inputs": scorer_inputs_from_variables(input_variables, run_variables, tool_names),
        }
        return output

    return _predict


@pytest.fixture(scope="session")
def evaluation_rows(cfg: RunnerConfig, predict_fn, _run_cache: dict) -> list[dict]:
    """Build one ``evaluate()``-ready row per golden.

    Forces ``predict_fn`` to run (and cache) each scenario up front, so every
    row's ``inputs`` already carries the resulting ``tool_calls``/``iterations``
    data the deterministic scorers need (see
    ``fluxnova_runner.agent_tool_calls.scorer_inputs_from_variables``), rather
    than just the bare ``input_variables`` the earlier, judge-only scorers
    needed. ``expectations`` carries the golden's reference answer for
    ``matches_golden``.
    """
    goldens = load_goldens(_GOLDENS_PATH)
    assert goldens, f"No goldens found at {_GOLDENS_PATH}"
    rows = []
    for golden in goldens:
        variables = _golden_to_variables(cfg, golden)
        predict_fn(variables)
        scorer_inputs = _run_cache[_cache_key(variables)]["scorer_inputs"]
        rows.append(
            {
                "inputs": scorer_inputs,
                "expectations": {"expected_output": golden["expected_output"]},
            }
        )
    return rows


@mlflow.test
def test_agent_reaches_evidence_backed_decision(evaluation_rows: list[dict], predict_fn) -> None:
    """Assert the loan-assessment agent's *actual* output on every golden still
    satisfies the shared ``decision_quality`` guideline judge.

    Note this does *not* compare against the golden's ``expected_output`` — that
    is what ``test_agent_matches_golden_decisions`` does. ``decision_quality``
    grades the output against fixed guidelines only: that it reaches a definitive
    APPROVE/REJECT recommendation backed by specific cited evidence (see
    ``fluxnova_mlflow_dataset.scorers.decision_quality``).

    This is MLflow's canonical regression-testing pattern: ``evaluate()`` drives
    the live agent per golden via ``predict_fn`` and scores its real output here
    — rather than merely re-scoring the golden's own reference answer.
    ``@mlflow.test`` tags this as a regression test run (run type ``test`` + a
    session id) and records its pass/fail status.
    """
    _log.info("Scoring %d golden(s) with decision_quality...", len(evaluation_rows))
    result = mlflow.genai.evaluate(
        data=evaluation_rows, predict_fn=predict_fn, scorers=[decision_quality]
    )

    # Guard against every scorer silently erroring (which leaves zero recorded
    # assessments and makes result.passed default to truthy): require a real
    # decision_quality verdict for every row before trusting the pass/fail.
    verdicts = result.tables["eval_results"]["decision_quality/value"]
    _log.info("decision_quality verdicts: %s", verdicts.tolist())
    assert verdicts.notna().all(), (
        "decision_quality did not produce a verdict for every golden — scoring "
        f"errored. Verdicts: {verdicts.tolist()}"
    )
    # Assert on the actual decision_quality verdicts rather than result.passed:
    # result.passed also inspects the expected_output expectation column (whose
    # value is the golden's free-text recommendation, not a yes/no rating), so it
    # reports false failures even when every scorer verdict is "yes".
    failed = verdicts[verdicts.str.lower() != "yes"]
    assert failed.empty, (
        f"decision_quality failed for {len(failed)} golden(s): {failed.tolist()}"
    )


@mlflow.test
def test_agent_matches_golden_decisions(evaluation_rows: list[dict], predict_fn) -> None:
    """Assert the loan-assessment agent's *actual* output on every golden matches
    that golden's ``expected_output`` via the shared ``matches_golden`` judge.

    Complements ``decision_quality`` (which grades the output against fixed
    guidelines, ignoring the golden): this scores the live agent output *against
    the scenario's reference answer*, returning a ``"yes"`` verdict only when both
    reach the same APPROVE/REJECT decision and cite the same categories of
    evidence (see ``fluxnova_mlflow_dataset.scorers.matches_golden``, which
    thresholds its 0.0-1.0 judge score at ``GOLDEN_MATCH_THRESHOLD``).
    ``@mlflow.test`` tags this as a regression test run and records its pass/fail
    status.
    """
    _log.info("Scoring %d golden(s) with matches_golden...", len(evaluation_rows))
    result = mlflow.genai.evaluate(
        data=evaluation_rows, predict_fn=predict_fn, scorers=[matches_golden]
    )

    # matches_golden returns None (recorded as NaN) when a golden lacks an
    # expected_output; every golden must have one for this gate to be meaningful.
    verdicts = result.tables["eval_results"]["matches_golden/value"]
    _log.info("matches_golden verdicts: %s", verdicts.tolist())
    assert verdicts.notna().all(), (
        "matches_golden did not produce a verdict for every golden — scoring "
        f"errored or a golden is missing expected_output. Verdicts: {verdicts.tolist()}"
    )
    # matches_golden now returns a "yes"/"no" pass/fail verdict (thresholded at
    # GOLDEN_MATCH_THRESHOLD inside the scorer, with the raw 0.0-1.0 score kept in
    # the feedback metadata), so gate on the verdict rather than a numeric score.
    failed = verdicts[verdicts.str.lower() != "yes"]
    assert failed.empty, (
        f"matches_golden scored below the {GOLDEN_MATCH_THRESHOLD} threshold for "
        f"{len(failed)} golden(s): {failed.tolist()}"
    )


def _assert_deterministic_scorer_passed(table, scorer_name: str) -> None:
    """Gate one deterministic scorer's column in an ``eval_results`` table.

    Handles every value shape ``fluxnova_mlflow_dataset.scorers`` returns for
    these scorers: plain booleans (possibly surfaced as their string form,
    e.g. ``"true"``/``"yes"``, depending on the store), graded 0.0-1.0 scores
    (``tool_correctness`` and friends — treated as a hard gate here, requiring
    the full 1.0, since this is a regression *gate* not a benchmark), and
    ``None``/``NaN`` for scorers that report "not applicable" for a given row
    (e.g. ``no_collateral_check_when_no_collateral`` when the applicant has no
    collateral) — never a failure.
    """
    column = f"{scorer_name}/value"
    if column not in table.columns:
        return  # scorer produced no column at all (shouldn't happen, but not this helper's job)
    values = table[column]

    def _passed(value: object) -> bool:
        if value is None or (isinstance(value, float) and value != value):  # NaN != itself
            return True  # not applicable for this row
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return float(value) >= 1.0
        return str(value).strip().lower() in {"true", "yes", "1"}

    failed = values[~values.apply(_passed)]
    assert failed.empty, (
        f"{scorer_name} failed for {len(failed)} golden(s): {failed.tolist()}"
    )


@mlflow.test
def test_agent_passes_deterministic_checks(evaluation_rows: list[dict], predict_fn) -> None:
    """Assert every golden's *actual* agent run passes the full deterministic
    scorer bundle (see ``fluxnova_mlflow_dataset.scorers.ALL_DETERMINISTIC_SCORERS``):
    states a definitive APPROVE/REJECT decision, called exactly the tools its
    applicant profile requires (and none it shouldn't), made no failed tool
    calls, called tools in the expected order, and — since content capture is
    enabled — passed each tool the arguments the BPMN wires up for it.

    These are the same deterministic scorers ``eval-service-worker`` and
    ``eval-trace-listener`` run, know nothing about tracing, and grade the
    ``tool_calls``/``iterations`` data ``evaluation_rows`` already collected
    from the live run's process variables (see
    ``fluxnova_runner.agent_tool_calls``) — no MLflow trace needed. A hard
    syntactic/structural complement to the ``decision_quality`` judge's opinion
    on whether the decision is well-reasoned. ``@mlflow.test`` tags this as a
    regression test run and records its pass/fail status.
    """
    _log.info(
        "Scoring %d golden(s) with the full deterministic scorer bundle...",
        len(evaluation_rows),
    )
    result = mlflow.genai.evaluate(
        data=evaluation_rows, predict_fn=predict_fn, scorers=ALL_DETERMINISTIC_SCORERS
    )

    table = result.tables["eval_results"]
    for scorer in ALL_DETERMINISTIC_SCORERS:
        _assert_deterministic_scorer_passed(table, scorer.name)


@mlflow.test
def test_agent_cites_gathered_evidence(evaluation_rows: list[dict], predict_fn) -> None:
    """Assert every golden's *actual* agent output cites the evidence it gathered,
    via the shared ``evidence_citation`` LLM judge (see
    ``fluxnova_mlflow_dataset.scorers``).

    Where ``decision_quality`` grades the *shape* of the recommendation and
    ``matches_golden`` compares it to the reference answer, ``evidence_citation``
    grades how well the final answer grounds its reasoning in the specific
    applicant/tool evidence — reading the agent's ``outputs`` plus the
    ``input_variables`` supplied per row (it needs no trace and treats the
    Fluxnova-only ``agent_goal`` as optional context). It returns a graded
    0.0-1.0 score, so this gate requires every row to meet
    ``_EVIDENCE_CITATION_THRESHOLD`` (env ``REGRESSION_EVIDENCE_CITATION_THRESHOLD``,
    default 0.7). ``@mlflow.test`` tags this as a regression test run and records
    its pass/fail status.
    """
    _log.info(
        "Scoring %d golden(s) with evidence_citation...", len(evaluation_rows)
    )
    result = mlflow.genai.evaluate(
        data=evaluation_rows, predict_fn=predict_fn, scorers=[evidence_citation]
    )

    scores = result.tables["eval_results"]["evidence_citation/value"]
    _log.info("evidence_citation scores: %s", scores.tolist())
    assert scores.notna().all(), (
        "evidence_citation did not produce a score for every golden — scoring "
        f"errored. Scores: {scores.tolist()}"
    )
    failed = scores[scores < _EVIDENCE_CITATION_THRESHOLD]
    assert failed.empty, (
        f"evidence_citation scored below the {_EVIDENCE_CITATION_THRESHOLD} "
        f"threshold for {len(failed)} golden(s): {failed.tolist()}"
    )
