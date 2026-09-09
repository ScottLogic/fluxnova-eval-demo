"""Score one just-completed agent trace with the shared deterministic scorers.

Deliberately trace-only: it takes an MLflow ``Trace`` object straight from the
trace store and runs ``fluxnova_mlflow_dataset.DETERMINISTIC_SCORERS`` against it
via ``mlflow.genai.evaluate(data=[{"trace": trace}], scorers=[...])``. Passing
the existing ``Trace`` that way attaches every scorer's ``Feedback`` back onto
that *same* real trace as an assessment and registers one MLflow "Evaluation
Run" grouping them — no BPMN parsing, no Fluxnova REST calls, no LLM judge (the
non-deterministic ``decision_quality`` judge is intentionally out of scope for
now — see the package README).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import mlflow
from fluxnova_mlflow_dataset import DETERMINISTIC_SCORERS


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
    """Deterministic scorers report a plain boolean ``Feedback`` value; MLflow may
    surface it as a real ``bool`` or its string form depending on the store.
    """
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


def score_trace(trace: Any, scorers: list[Any] | None = None) -> TraceEvalOutcome:
    """Run the deterministic scorers against ``trace`` and return the outcome.

    ``scorers`` defaults to the shared ``DETERMINISTIC_SCORERS`` — injectable so
    tests can pass stubs and future callers can narrow the set.

    Raises :class:`ScoringError` if MLflow produced no ``eval_results`` for the
    trace (rather than surfacing a bare ``KeyError``), so the caller can retry or
    skip without crashing its poll loop.
    """
    scorers = DETERMINISTIC_SCORERS if scorers is None else scorers
    result = mlflow.genai.evaluate(data=[{"trace": trace}], scorers=scorers)

    table = result.tables.get("eval_results")
    if table is None or len(table) == 0:
        raise ScoringError(
            f"mlflow.genai.evaluate returned no eval_results for trace "
            f"{trace.info.trace_id} — its span data was likely unavailable in the "
            "tracking store at scoring time."
        )
    row = table.iloc[0]

    scorer_results = {
        s.name: {"value": row[f"{s.name}/value"], "rationale": row.get(f"{s.name}/rationale")}
        for s in scorers
    }
    passed = all(_passed(res["value"]) for res in scorer_results.values())
    return TraceEvalOutcome(
        trace_id=trace.info.trace_id,
        passed=passed,
        scorer_results=scorer_results,
    )
