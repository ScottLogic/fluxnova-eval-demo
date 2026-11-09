"""Tests for the BPMN-configurable guardrail thresholds."""

from __future__ import annotations

import pytest

from eval_service_worker.guardrail import (
    GuardrailConfigError,
    GuardrailThresholds,
    apply_guardrail,
)
from eval_service_worker.scoring import _scorer_passed

KNOWN = {"decision_quality", "no_tool_errors", "step_efficiency", "tool_correctness"}


def _results(**values) -> dict:
    return {name: {"value": value, "rationale": f"{name} rationale"} for name, value in values.items()}


def test_default_requires_every_applicable_scorer() -> None:
    results = _results(decision_quality="yes", no_tool_errors=True, step_efficiency=False)
    outcome = apply_guardrail(results, GuardrailThresholds(), _scorer_passed)
    assert outcome.passed is False
    assert outcome.score == pytest.approx(2 / 3)
    assert outcome.failed == ("step_efficiency",)


def test_not_applicable_scorers_are_left_out_of_the_score() -> None:
    results = _results(decision_quality="yes", no_tool_errors=True, step_efficiency=None)
    outcome = apply_guardrail(results, GuardrailThresholds(), _scorer_passed)
    assert outcome.passed is True
    assert outcome.score == 1.0


def test_lower_min_score_tolerates_failures() -> None:
    results = _results(
        decision_quality="yes", no_tool_errors=True, step_efficiency=False, tool_correctness=True
    )
    outcome = apply_guardrail(results, GuardrailThresholds(min_score=0.75), _scorer_passed)
    assert outcome.passed is True
    assert outcome.failed == ("step_efficiency",)


def test_required_scorer_fails_run_whatever_the_score() -> None:
    results = _results(
        decision_quality="no", no_tool_errors=True, step_efficiency=True, tool_correctness=True
    )
    thresholds = GuardrailThresholds(min_score=0.5, required_scorers=("decision_quality",))
    outcome = apply_guardrail(results, thresholds, _scorer_passed)
    assert outcome.passed is False
    assert outcome.required_failed == ("decision_quality",)


def test_not_applicable_required_scorer_does_not_fail_run() -> None:
    results = _results(decision_quality="yes", step_efficiency=None)
    thresholds = GuardrailThresholds(required_scorers=("step_efficiency",))
    assert apply_guardrail(results, thresholds, _scorer_passed).passed is True


def test_thresholds_parse_numbers_strings_and_lists() -> None:
    variables = {"evalMinScore": "0.8", "evalRequiredScorers": " decision_quality , no_tool_errors "}
    thresholds = GuardrailThresholds.from_task_variables(variables.get, KNOWN)
    assert thresholds == GuardrailThresholds(0.8, ("decision_quality", "no_tool_errors"))


def test_missing_or_blank_thresholds_use_defaults() -> None:
    assert GuardrailThresholds.from_task_variables({}.get, KNOWN) == GuardrailThresholds()
    blank = {"evalMinScore": "", "evalRequiredScorers": ""}
    assert GuardrailThresholds.from_task_variables(blank.get, KNOWN) == GuardrailThresholds()


@pytest.mark.parametrize(
    "variables",
    [
        {"evalMinScore": "abc"},
        {"evalMinScore": -0.1},
        {"evalMinScore": float("nan")},
        {"evalRequiredScorers": "typo_scorer"},
        {"evalRequiredScorers": 3},
    ],
)
def test_invalid_thresholds_are_rejected(variables) -> None:
    with pytest.raises(GuardrailConfigError):
        GuardrailThresholds.from_task_variables(variables.get, KNOWN)
