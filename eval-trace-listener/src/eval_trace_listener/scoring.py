"""Score one just-completed agent trace with the shared scorers.

Takes an MLflow ``Trace`` object straight from the trace store, extracts the
plain values the scorers need (via
``fluxnova_mlflow_dataset.scorer_inputs_from_trace`` — the scorers themselves
know nothing about tracing) and runs the :data:`LISTENER_SCORERS` bundle against
them via ``mlflow.genai.evaluate``. The row still carries the original ``trace``
so every scorer's ``Feedback`` is logged back onto that *same* real trace as an
assessment and one MLflow "Evaluation Run" grouping them is registered — no BPMN
parsing, no Fluxnova REST calls.

:data:`LISTENER_SCORERS` is the shared ``DETERMINISTIC_SCORERS`` plus the two LLM
judges that need only trace-derivable data — ``decision_quality`` (a Guidelines
judge over the final ``outputs``) and ``evidence_citation`` (over ``outputs`` +
the extracted ``input_variables``). Both call the provider selected by
``fluxnova_mlflow_dataset.scorers.LLM_JUDGE_PROVIDER`` (``LLM_JUDGE_PROVIDER`` env
var, default/currently ``openai``, calling OpenAI's API directly rather than a
local Ollama model — set it to ``ollama`` for a fully local judge instead), so
the listener host must be able to reach whichever provider that resolves to.
``matches_golden`` is *not* included: it needs a golden ``expected_output`` (an
``expectations`` value) that a bare trace doesn't carry — that judge lives in the
regression suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import mlflow
from fluxnova_mlflow_dataset import (
    DETERMINISTIC_SCORERS,
    decision_quality,
    evidence_citation,
    final_output_from_spans,
    scorer_inputs_from_trace,
)

# The scorers this service runs by default: the deterministic checks plus the two
# LLM judges whose inputs are all derivable from the trace (decision_quality over
# outputs, evidence_citation over outputs + input_variables). matches_golden is
# excluded — it needs a golden expected_output the trace doesn't carry.
LISTENER_SCORERS: list[Any] = [decision_quality, evidence_citation, *DETERMINISTIC_SCORERS]


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

    Covers every value shape in :data:`LISTENER_SCORERS`: the deterministic
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


def score_trace(trace: Any, scorers: list[Any] | None = None) -> TraceEvalOutcome:
    """Run the :data:`LISTENER_SCORERS` bundle against ``trace`` and return the outcome.

    ``scorers`` defaults to :data:`LISTENER_SCORERS` (deterministic checks plus
    the ``decision_quality`` and ``evidence_citation`` LLM judges) — injectable
    so tests can pass stubs and callers can narrow the set.

    Raises :class:`ScoringError` if MLflow produced no ``eval_results`` for the
    trace (rather than surfacing a bare ``KeyError``), so the caller can retry or
    skip without crashing its poll loop.
    """
    scorers = LISTENER_SCORERS if scorers is None else scorers
    spans = trace.data.spans
    row = {
        "trace": trace,
        "inputs": scorer_inputs_from_trace(trace),
        "outputs": final_output_from_spans(spans),
    }
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
