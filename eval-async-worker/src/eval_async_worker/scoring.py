"""Score one agent run with the shared scorers.

The scorer inputs and final output come from the run's **process variables**
(``fluxnova_mlflow_dataset.load_agent_run``), never from trace content, so gen_ai
content capture can stay off. The run's MLflow ``Trace`` is passed alongside only
as the anchor: ``mlflow.genai.evaluate`` logs every scorer's ``Feedback`` onto
that same trace as an assessment, grouped under one MLflow "Evaluation Run",
without copying the inputs/outputs into MLflow.

:data:`ASYNC_EVAL_SCORERS` is the shared ``DETERMINISTIC_SCORERS`` plus two LLM
judges — ``decision_quality`` (a Guidelines judge over the final ``outputs``)
and ``evidence_citation`` (over ``outputs`` + the ``input_variables``). Both use
the shared judge provider (OpenAI by default, optionally Ollama).
``matches_golden`` is *not* included: it needs a golden ``expected_output`` that
a production run doesn't have — that judge lives in the regression suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import mlflow
from fluxnova_mlflow_dataset import (
    DETERMINISTIC_SCORERS,
    decision_quality,
    evidence_citation,
)

# The scorers this service runs by default: the deterministic checks plus the two
# LLM judges whose inputs are all derivable from the trace (decision_quality over
# outputs, evidence_citation over outputs + input_variables). matches_golden is
# excluded — it needs a golden expected_output the trace doesn't carry.
ASYNC_EVAL_SCORERS: list[Any] = [decision_quality, evidence_citation, *DETERMINISTIC_SCORERS]


@dataclass
class TraceEvalOutcome:
    """The result of scoring one agent trace."""

    trace_id: str
    passed: bool
    # One entry per scorer that ran, each {"value": ..., "rationale": ...}.
    scorer_results: dict[str, dict[str, Any]]

    def summary(self) -> str:
        """A compact ``name=value`` line for logging."""
        return ", ".join(f"{name}={res['value']}" for name, res in self.scorer_results.items())


class ScoringError(Exception):
    """Raised when a trace could not be scored (e.g. MLflow returned no results).

    Typically because ``mlflow.genai.evaluate`` couldn't fetch the trace's span
    data from the tracking store (``RESOURCE_DOES_NOT_EXIST`` — an async-write
    race for a just-landed trace, or a trace whose data was pruned), so its
    result carries no ``eval_results`` table. The caller decides whether to retry.
    """


def _passed(value: Any) -> bool:
    """Decide whether one scorer's raw ``Feedback`` value counts as a pass.

    Covers every value shape in :data:`ASYNC_EVAL_SCORERS`: the deterministic
    checks report a plain boolean (surfaced as a real ``bool`` or its string
    form depending on the store); ``decision_quality`` reports a categorical
    ``"yes"``/``"no"`` string; the graded scorers (``tool_correctness``,
    ``evidence_citation``) report a 0.0-1.0 float, where any non-zero score
    counts as a (partial) pass. ``None`` (a "not applicable" verdict) passes
    through so an inapplicable scorer never fails a run.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


def score_trace(
    trace: Any,
    inputs: dict[str, Any],
    outputs: str | None,
    scorers: list[Any] | None = None,
) -> TraceEvalOutcome:
    """Run the :data:`ASYNC_EVAL_SCORERS` bundle over ``inputs``/``outputs`` and
    record the feedback on ``trace``.

    ``scorers`` defaults to :data:`ASYNC_EVAL_SCORERS` (deterministic checks plus
    the ``decision_quality`` and ``evidence_citation`` LLM judges) — injectable
    so tests can pass stubs and callers can narrow the set.

    Raises :class:`ScoringError` if MLflow produced no ``eval_results`` for the
    trace (rather than surfacing a bare ``KeyError``), so the caller can retry or
    fail the task without crashing the worker.
    """
    scorers = ASYNC_EVAL_SCORERS if scorers is None else scorers
    row = {"trace": trace, "inputs": inputs, "outputs": outputs}
    result = mlflow.genai.evaluate(data=[row], scorers=scorers)

    table = result.tables.get("eval_results")
    if table is None or len(table) == 0:
        raise ScoringError(
            f"mlflow.genai.evaluate returned no eval_results for trace "
            f"{trace.info.trace_id} — its span data was likely unavailable in the "
            "tracking store at scoring time."
        )
    row = table.iloc[0]

    scorer_results = {
        s.name: {"value": row.get(f"{s.name}/value"), "rationale": row.get(f"{s.name}/rationale")}
        for s in scorers
    }
    passed = all(_passed(res["value"]) for res in scorer_results.values())
    return TraceEvalOutcome(
        trace_id=trace.info.trace_id,
        passed=passed,
        scorer_results=scorer_results,
    )
