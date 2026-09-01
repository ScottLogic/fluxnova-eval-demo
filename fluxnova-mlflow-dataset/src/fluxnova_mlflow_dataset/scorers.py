"""Shared MLflow-native judge definitions.

Kept in one place so the *same* judge definition (guideline text, name) is used
identically by:

- the offline batch regression/analysis suite (``harness/src/mlflow_eval/main.py``,
  ``mlflow-eval`` CLI), and
- the synchronous ``eval-service-worker`` (a BPMN external-task worker that scores
  one just-completed subprocess run on demand — see ``EVAL-SERVICE-WORKER-PLAN.md``).

Avoids the guideline text drifting between the two call sites.
"""

from __future__ import annotations

import re

from mlflow.entities import Feedback
from mlflow.genai.scorers import Guidelines, scorer

from fluxnova_mlflow_dataset.traces import (
    final_output_from_spans,
    input_variables_from_spans,
    tool_calls_from_spans,
)

DECISION_QUALITY_NAME = "decision_quality"

DECISION_QUALITY_GUIDELINES = [
    "The final output must reach a definitive APPROVE or REJECT lending recommendation. "
    "Vague conclusions or deferred decisions such as 'next steps required' do not satisfy "
    "this guideline.",
    "The final output must state its recommendation backed by evidence: it must cite "
    "specific data points gathered during the assessment, such as credit score, fraud "
    "risk, affordability result, or employment status.",
]


def decision_quality_judge(model: str) -> Guidelines:
    """Build the ``decision_quality`` ``Guidelines`` judge for the given model URI.

    ``model`` differs by call site: a direct ``"<provider>:/<model>"`` URI (e.g.
    ``"ollama:/llama3.2"``) for offline batch evaluation, or a
    ``"gateway:/<endpoint>"`` URI for anything routed through the MLflow AI
    Gateway (automatic/online scoring, and the synchronous eval-service-worker).
    """
    return Guidelines(
        name=DECISION_QUALITY_NAME, guidelines=DECISION_QUALITY_GUIDELINES, model=model
    )


# ---------------------------------------------------------------------------
# Deterministic (non-LLM) scorers — trace-only, for eval-service-worker.
#
# Unlike `harness/src/mlflow_eval/main.py`'s deterministic scorers (which read
# `expected_tools`/`available_tools` straight out of the workflow YAML config),
# these are self-contained: the tool-call/applicant-profile rules below are a
# hardcoded mirror of `harness/config/loan-assesment-eval.yml`'s `expected_tools`
# list, kept in sync manually. This keeps eval-service-worker trace-only (no
# BPMN/YAML config read at runtime) at the cost of needing a manual update here
# if that BPMN's tool set/rules ever change. See EVAL-SERVICE-WORKER-PLAN.md.
#
# Each takes MLflow's `trace` parameter directly (rather than `inputs`/
# `outputs`) so `mlflow.genai.evaluate(data=[{"trace": trace}], scorers=[...])`
# logs every scorer's ``Feedback`` back onto that *same* real trace, and groups
# them together as one MLflow "Evaluation Run" — see eval_service_worker.scoring.
# ---------------------------------------------------------------------------

_ALWAYS_REQUIRED_TOOLS = ("Check Credit Score", "Run Fraud Screening", "Assess Affordability")
_DECISION_KEYWORD_RE = re.compile(r"\b(APPROVE|REJECT)\b", re.IGNORECASE)


def _expected_tools_for(variables: dict) -> tuple[set[str], set[str]]:
    """Return ``(required, forbidden)`` tool display-names for one applicant profile."""
    required = set(_ALWAYS_REQUIRED_TOOLS)
    forbidden: set[str] = set()
    if variables.get("applicantType") == "EMPLOYED":
        required.add("Verify Employment")
        forbidden.add("Analyse Bank Statements")
    else:
        required.add("Analyse Bank Statements")
        forbidden.add("Verify Employment")
    if variables.get("hasCollateral"):
        required.add("Value Collateral")
    else:
        forbidden.add("Value Collateral")
    return required, forbidden


@scorer
def required_tools_called(trace) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """Deterministic check: were exactly the tools this applicant's profile requires
    called (and none of the ones that shouldn't be), per ``_expected_tools_for``?
    """
    spans = trace.data.spans
    variables = input_variables_from_spans(spans)
    called = {c.tool_name for c in tool_calls_from_spans(spans) if c.status == "OK"}
    required, forbidden = _expected_tools_for(variables)
    missing = required - called
    unexpected = forbidden & called
    passed = not missing and not unexpected
    problems = []
    if missing:
        problems.append(f"missing required tool call(s): {sorted(missing)}")
    if unexpected:
        problems.append(f"unexpected tool call(s) for this applicant profile: {sorted(unexpected)}")
    return Feedback(
        value=passed,
        rationale="; ".join(problems)
        or "All tools required for this applicant profile were called, and no unexpected ones were.",
    )


@scorer
def no_tool_errors(trace) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """Deterministic check: did every tool call the agent made succeed
    (no ``execute_tool`` span errors)?
    """
    failed = [c.tool_name for c in tool_calls_from_spans(trace.data.spans) if c.status != "OK"]
    passed = not failed
    return Feedback(
        value=passed,
        rationale="No tool call errors." if passed else f"Tool call(s) failed: {failed}",
    )


@scorer
def definitive_decision_stated(trace) -> Feedback:  # noqa: ANN001 - MLflow scorer signature
    """Deterministic check: does the final output literally contain an APPROVE or
    REJECT keyword? A hard syntactic check, complementing (not replacing) the
    ``decision_quality`` LLM judge's opinion on whether it's well-reasoned.
    """
    output = final_output_from_spans(trace.data.spans) or ""
    matched = bool(_DECISION_KEYWORD_RE.search(output))
    return Feedback(
        value=matched,
        rationale=(
            "Final output states a definitive APPROVE/REJECT keyword."
            if matched
            else "Final output does not contain a definitive APPROVE or REJECT keyword."
        ),
    )


DETERMINISTIC_SCORERS = [required_tools_called, no_tool_errors, definitive_decision_stated]
