"""Scores one just-completed agentic subprocess run against a set of scorers —
the nondeterministic ``decision_quality`` LLM judge plus trace-only
deterministic checks (required tool calls, no tool errors, a definitive
decision keyword) — reading trace data only (no BPMN parsing, no Fluxnova REST
API calls). See EVAL-SERVICE-WORKER-PLAN.md.

Uses ``mlflow.genai.evaluate(data=[{"trace": trace}], scorers=[...])`` (rather
than a bare ``mlflow.log_feedback`` call per scorer) so that:

- every scorer's ``Feedback`` is logged back onto the *same* real agentic
  subprocess trace (confirmed empirically — passing an existing ``Trace``
  object via the ``trace`` column attaches assessments to it directly, not to
  a newly-synthesized one), and
- MLflow registers a proper "Evaluation Run" grouping all of them together
  (visible under MLflow's Evaluations UI) — not just isolated per-trace
  assessments with no run to group them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import mlflow
from fluxnova_mlflow_dataset import (
    DETERMINISTIC_SCORERS,
    MlflowTraceReader,
    decision_quality_judge,
    experiment_name_for,
    write_to_mlflow_dataset,
)

# The Guidelines judge reports a categorical "yes"/"no" adherence value (not a
# numeric score) — confirmed by inspecting a real logged `decision_quality`
# assessment during this session's investigation. Deterministic scorers report
# plain booleans instead (see fluxnova_mlflow_dataset.scorers).
_PASS_VALUE = "yes"

_DECISION_QUALITY_NAME = "decision_quality"

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
    # One entry per scorer that ran (including decision_quality), each
    # {"value": ..., "rationale": ...} — lets callers/tests see every check's
    # result, not just the one (decision_quality) that gates the BPMN gateway.
    scorer_results: dict[str, dict[str, Any]]


def score_process_instance(
    process_instance_id: str,
    *,
    tracking_uri: str,
    process_key: str,
    experiment_name: str | None,
    judge_model: str,
    trace_poll_timeout: float = 30.0,
    trace_poll_interval: float = 3.0,
) -> EvalOutcome:
    """Fetch a completed subprocess run's trace from MLflow, run the
    ``decision_quality`` judge plus the deterministic scorers against it, and
    record the results.

    Logs every scorer's ``Feedback`` back onto the trace as an assessment and
    registers one MLflow Evaluation Run grouping them, merges a lightweight
    record into the MLflow evaluation dataset, then returns the pass/fail
    outcome for the caller (the BPMN worker) to act on — gating is still
    driven solely by ``decision_quality`` (the only nondeterministic/judgement
    call among the scorers); the deterministic scorers are recorded for
    visibility, not (yet) wired into the BPMN gateway condition.

    ``trace_poll_timeout``/``trace_poll_interval`` control how long to retry
    looking up the trace before giving up — the OTel Collector delivers spans
    to MLflow asynchronously, so this BPMN service task (which runs immediately
    after the subprocess ends) can otherwise beat the trace's arrival.
    """
    mlflow.set_tracking_uri(tracking_uri)
    experiment = mlflow.set_experiment(experiment_name_for(process_key, experiment_name))

    reader = MlflowTraceReader(tracking_uri, experiment.experiment_id)
    trace = reader.wait_for_trace(
        process_instance_id, timeout=trace_poll_timeout, poll_interval=trace_poll_interval
    )
    final_output = reader.get_final_output(process_instance_id)
    if not final_output:
        raise NoFinalOutputError(
            f"No final output found for process instance {process_instance_id!r} — "
            "has the agentic subprocess actually completed and been exported to "
            "MLflow yet?"
        )

    scorers = [decision_quality_judge(judge_model), *DETERMINISTIC_SCORERS]
    result = mlflow.genai.evaluate(data=[{"trace": trace}], scorers=scorers)
    row = result.tables["eval_results"].iloc[0]

    scorer_results = {
        s.name: {"value": row[f"{s.name}/value"], "rationale": row.get(f"{s.name}/rationale")}
        for s in scorers
    }

    decision_quality = scorer_results[_DECISION_QUALITY_NAME]
    eval_passed = str(decision_quality["value"]).strip().lower() == _PASS_VALUE
    rationale = decision_quality["rationale"] or ""

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
    """Merge a lightweight evaluation-dataset record for this run.

    Unlike ``fluxnova_mlflow_dataset.store.build_mlflow_record`` (used by the
    offline collector), this worker has no BPMN/Fluxnova REST access to enrich
    the record with ``agent_goal``/``input_variables``/``tool_calls`` — only
    the trace-derived output and every scorer's verdict are recorded.
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
        "outputs": final_output,
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
