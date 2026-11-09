"""Scores one just-completed agentic subprocess run against a set of scorers —
the nondeterministic ``decision_quality`` LLM judge plus deterministic checks
(required tool calls, no tool errors, a definitive decision keyword).

Scorer inputs come from the agent run's **process variables**
(``fluxnova_mlflow_dataset.load_agent_run``: conversation history, loop count and
``agent:context`` variables), never from trace content, so gen_ai content capture
can stay off. The run's MLflow trace is still looked up, but only as the anchor
that scorer feedback is attached to: passing it to ``mlflow.genai.evaluate``
attaches the assessments to it without copying the inputs/outputs into MLflow.

Uses ``mlflow.genai.evaluate(data=[{"trace": trace, "inputs": ...,
"outputs": ...}], scorers=[...])`` (rather than a bare ``mlflow.log_feedback``
call per scorer) so that:

- every scorer's ``Feedback`` is logged back onto the *same* real agentic
  subprocess trace (confirmed empirically — including the ``trace`` column
  attaches assessments to it directly, not to a newly-synthesized one,
  regardless of which columns the scorers actually read), and
- MLflow registers a proper "Evaluation Run" grouping all of them together
  (visible under MLflow's Evaluations UI) — not just isolated per-trace
  assessments with no run to group them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import mlflow
from fluxnova_mlflow_dataset import (
    DETERMINISTIC_SCORERS,
    FluxnovaClient,
    MlflowTraceReader,
    decision_keyword,
    decision_quality_judge,
    experiment_name_for,
    load_agent_run,
    write_to_mlflow_dataset,
)

from eval_service_worker.guardrail import GuardrailThresholds, apply_guardrail

# The Guidelines judge reports a categorical "yes"/"no" adherence value (not a
# numeric score) — confirmed by inspecting a real logged `decision_quality`
# assessment during this session's investigation. Deterministic scorers report
# plain booleans instead (see fluxnova_mlflow_dataset.scorers).
_PASS_VALUE = "yes"

_DECISION_QUALITY_NAME = "decision_quality"


def _scorer_passed(name: str, value: Any) -> bool:
    """Return whether one scorer's raw value counts as a pass.

    ``decision_quality`` (the Guidelines judge) reports a categorical
    ``"yes"``/``"no"`` string; the deterministic scorers report plain booleans.

    A scorer may also report *no verdict* — ``None`` (surfaced as ``NaN`` in the
    result table, or as a missing column when it's the only value) — meaning the
    check was **not applicable** to this run (e.g.
    ``no_verify_employment_for_self_employed_applicant`` skips EMPLOYED
    applicants). A not-applicable verdict must never fail the eval, so it counts
    as a pass.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return True
    if name == _DECISION_QUALITY_NAME:
        return str(value).strip().lower() == _PASS_VALUE
    return bool(value)

# Tag value used to distinguish worker-triggered dataset records from ones
# written by MLflow's built-in automatic-judge scheduler (which uses the same
# judge name but runs on a sample of traces, unprompted).
_SOURCE_TAG = "eval-service-worker"


class NoFinalOutputError(Exception):
    """Raised when the completed subprocess run has no output text to judge yet."""


@dataclass
class EvalOutcome:
    """The result of scoring one process instance's agentic subprocess run."""

    process_instance_id: str
    eval_passed: bool
    eval_rationale: str
    final_output: str
    # Fraction of applicable scorers that passed (compared with evalMinScore).
    eval_score: float
    # Applicable scorers that failed, whether or not the run still passed.
    failed_scorers: tuple[str, ...]
    # One entry per scorer that ran (including decision_quality), each
    # {"value": ..., "rationale": ...} — every one of these checks (the
    # decision_quality judge and the deterministic scorers) must pass for
    # eval_passed to be True.
    scorer_results: dict[str, dict[str, Any]]


def score_process_instance(
    process_instance_id: str,
    *,
    client: FluxnovaClient,
    tracking_uri: str,
    process_key: str,
    experiment_name: str | None,
    judge_model: str,
    trace_poll_timeout: float = 30.0,
    trace_poll_interval: float = 3.0,
    thresholds: GuardrailThresholds | None = None,
) -> EvalOutcome:
    """Read a completed subprocess run's process variables from Fluxnova, run
    the ``decision_quality`` judge plus the deterministic scorers against them,
    and record the results on the run's MLflow trace.

    Logs every scorer's ``Feedback`` back onto the trace as an assessment and
    registers one MLflow Evaluation Run grouping them, merges a lightweight
    record into the MLflow evaluation dataset, then returns the pass/fail
    outcome for the caller (the BPMN worker) to act on — gating requires *every*
    scorer to pass: both the nondeterministic ``decision_quality`` judge and all
    of the deterministic trace-only scorers.

    ``trace_poll_timeout``/``trace_poll_interval`` control how long to retry
    looking up the trace before giving up — the OTel Collector delivers spans
    to MLflow asynchronously, so this BPMN service task (which runs immediately
    after the subprocess ends) can otherwise beat the trace's arrival.
    """
    run = load_agent_run(client, process_instance_id)
    final_output = run.outputs
    if not final_output:
        raise NoFinalOutputError(
            f"No final output found for process instance {process_instance_id!r} — "
            "has the agentic subprocess actually completed?"
        )

    mlflow.set_tracking_uri(tracking_uri)
    experiment = mlflow.set_experiment(experiment_name_for(process_key, experiment_name))

    reader = MlflowTraceReader(tracking_uri, experiment.experiment_id)
    trace = reader.wait_for_trace(
        process_instance_id, timeout=trace_poll_timeout, poll_interval=trace_poll_interval
    )

    scorers = [decision_quality_judge(judge_model), *DETERMINISTIC_SCORERS]
    row = {"trace": trace, "inputs": run.inputs, "outputs": final_output}
    result = mlflow.genai.evaluate(data=[row], scorers=scorers)
    row = result.tables["eval_results"].iloc[0]

    scorer_results = {
        s.name: {"value": row.get(f"{s.name}/value"), "rationale": row.get(f"{s.name}/rationale")}
        for s in scorers
    }

    thresholds = thresholds or GuardrailThresholds()
    guardrail = apply_guardrail(scorer_results, thresholds, _scorer_passed)
    eval_passed = guardrail.passed
    failures = "; ".join(
        f"{name}: {scorer_results[name]['rationale'] or 'failed'}" for name in guardrail.failed
    )

    if eval_passed and not guardrail.failed:
        decision_quality = scorer_results[_DECISION_QUALITY_NAME]
        rationale = (
            decision_quality["rationale"]
            or "All deterministic and non-deterministic evaluation checks passed."
        )
    elif eval_passed:
        rationale = (
            f"Passed with score {guardrail.score:.2f} (minimum {thresholds.min_score:.2f}). "
            f"Tolerated failures: {failures}"
        )
    elif guardrail.required_failed:
        rationale = f"Required scorer(s) failed: {', '.join(guardrail.required_failed)}. {failures}"
    else:
        rationale = (
            f"Score {guardrail.score:.2f} is below the minimum {thresholds.min_score:.2f}. {failures}"
        )

    _log_dataset_record(
        process_key=process_key,
        experiment_name=experiment_name,
        tracking_uri=tracking_uri,
        process_instance_id=process_instance_id,
        final_output=final_output,
        judge_model=judge_model,
        scorer_results=scorer_results,
    )

    return EvalOutcome(
        process_instance_id=process_instance_id,
        eval_passed=eval_passed,
        eval_rationale=rationale,
        final_output=final_output,
        scorer_results=scorer_results,
        eval_score=guardrail.score,
        failed_scorers=guardrail.failed,
    )


def _log_dataset_record(
    *,
    process_key: str,
    experiment_name: str | None,
    tracking_uri: str,
    process_instance_id: str,
    final_output: str,
    judge_model: str,
    scorer_results: dict[str, dict[str, Any]],
) -> None:
    """Merge a lightweight, content-free evaluation-dataset record for this run.

    Only the decision keyword (``APPROVE``/``REJECT``) and every scorer's verdict
    and rationale are recorded — never the agent's full response or the
    applicant inputs, which stay in Fluxnova's process variables.
    """
    tags = {
        "processInstanceId": process_instance_id,
        "processKey": process_key,
        "source": _SOURCE_TAG,
        "judge_model": judge_model,
    }
    for name, outcome in scorer_results.items():
        tags[name] = str(outcome["value"])
        tags[f"{name}_rationale"] = outcome["rationale"] or ""

    record = {
        "inputs": {"process_instance_id": process_instance_id},
        "outputs": decision_keyword(final_output),
        "expectations": {},
        "tags": tags,
    }
    write_to_mlflow_dataset(
        tracking_uri=tracking_uri,
        process_key=process_key,
        dataset_name=None,
        record=record,
        skip_if_exists=False,
        experiment_name=experiment_name,
    )
