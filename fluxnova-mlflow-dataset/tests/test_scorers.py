"""Tests for the deterministic, value-based scorers in ``scorers.py``.

Each scorer knows nothing about tracing: it reads plain values from MLflow's
``inputs``/``outputs`` columns. These tests build those payloads directly (the
canonical ``inputs`` shape ``scorer_inputs_from_trace`` produces) and assert each
scorer's ``Feedback`` value — including the "not applicable" ``None`` returns for
tool-argument scorers when content capture is disabled.
"""

from __future__ import annotations

from typing import Any

from fluxnova_mlflow_dataset.scorers import (
    affordability_called_after_income_confirmed,
    all_tool_calls_completed,
    collateral_valuation_called_correctly_when_required,
    definitive_decision_stated,
    no_bank_statement_for_employed_applicant,
    no_collateral_check_when_no_collateral,
    no_tool_errors,
    no_verify_employment_for_self_employed_applicant,
    requested_amount_passed_to_affordability,
    required_tools_called,
    step_efficiency,
    tool_argument_correctness,
    tool_correctness,
)


def _tool(name: str, *, status: str = "OK", arguments: dict | None = None) -> dict:
    """One tool-call record in the canonical scorer ``inputs`` shape."""
    return {"name": name, "status": status, "arguments": arguments}


def _inputs(
    *,
    variables: dict | None = None,
    tool_calls: list[dict] | None = None,
    iterations: int | None = None,
) -> dict:
    return {
        "input_variables": variables or {},
        "tool_calls": tool_calls or [],
        "iterations": iterations,
    }


def _value(result: Any) -> Any:
    """Extract a scorer's raw feedback value, or ``None`` when it returned None."""
    return None if result is None else result.feedback.value


_EMPLOYED_NO_COLLATERAL = {
    "applicantType": "EMPLOYED",
    "hasCollateral": False,
    "customerId": "C1",
    "applicationId": "A1",
    "requestedAmount": 5000,
}


def _full_employed_calls(*, arguments: bool = False) -> list[dict]:
    """The tools an EMPLOYED, no-collateral applicant should trigger, in order."""
    args = {
        "Check Credit Score": {"customerId": "C1"},
        "Run Fraud Screening": {"applicationId": "A1", "customerId": "C1"},
        "Verify Employment": {"customerId": "C1"},
        "Assess Affordability": {"customerId": "C1", "requestedAmount": 5000},
    }
    names = ["Check Credit Score", "Run Fraud Screening", "Verify Employment", "Assess Affordability"]
    return [_tool(name, arguments=args[name] if arguments else None) for name in names]


class TestRequiredToolsCalled:
    def test_pass_when_all_required_called(self):
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=_full_employed_calls())
        assert _value(required_tools_called(inputs=inputs)) is True

    def test_fail_when_required_missing(self):
        calls = _full_employed_calls()[:-1]  # drop Assess Affordability
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=calls)
        assert _value(required_tools_called(inputs=inputs)) is False

    def test_fail_when_forbidden_tool_called(self):
        calls = [*_full_employed_calls(), _tool("Analyse Bank Statements")]
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=calls)
        assert _value(required_tools_called(inputs=inputs)) is False


class TestToolCorrectness:
    def test_full_score_when_exact(self):
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=_full_employed_calls())
        assert _value(tool_correctness(inputs=inputs)) == 1.0

    def test_partial_score_when_missing(self):
        calls = _full_employed_calls()[:-1]
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=calls)
        assert _value(tool_correctness(inputs=inputs)) < 1.0


class TestNoToolErrors:
    def test_pass_when_all_ok(self):
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=_full_employed_calls())
        assert _value(no_tool_errors(inputs=inputs)) is True

    def test_fail_on_error_status(self):
        calls = [_tool("Check Credit Score", status="ERROR")]
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=calls)
        assert _value(no_tool_errors(inputs=inputs)) is False


class TestAllToolCallsCompleted:
    def test_pass_when_all_ok(self):
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=_full_employed_calls())
        assert _value(all_tool_calls_completed(inputs=inputs)) is True

    def test_fail_on_error(self):
        calls = [_tool("Check Credit Score", status="ERROR")]
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=calls)
        assert _value(all_tool_calls_completed(inputs=inputs)) is False


class TestDefinitiveDecisionStated:
    def test_pass_when_keyword_present(self):
        assert _value(definitive_decision_stated(outputs="APPROVE: strong credit")) is True

    def test_fail_when_no_keyword(self):
        assert _value(definitive_decision_stated(outputs="Further review needed")) is False

    def test_handles_none_output(self):
        assert _value(definitive_decision_stated(outputs=None)) is False

    def test_handles_non_string_output(self):
        assert _value(definitive_decision_stated(outputs={"decision": "REJECT"})) is True


class TestProfileForbiddenTools:
    def test_no_collateral_check_none_when_has_collateral(self):
        variables = {**_EMPLOYED_NO_COLLATERAL, "hasCollateral": True}
        inputs = _inputs(variables=variables, tool_calls=[])
        assert no_collateral_check_when_no_collateral(inputs=inputs) is None

    def test_no_collateral_check_fails_when_called(self):
        calls = [_tool("Value Collateral")]
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=calls)
        assert _value(no_collateral_check_when_no_collateral(inputs=inputs)) is False

    def test_no_collateral_check_ok_when_not_called(self):
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=[])
        assert _value(no_collateral_check_when_no_collateral(inputs=inputs)) is True

    def test_no_bank_statement_fails_for_employed(self):
        calls = [_tool("Analyse Bank Statements")]
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=calls)
        assert _value(no_bank_statement_for_employed_applicant(inputs=inputs)) is False

    def test_no_bank_statement_none_for_self_employed(self):
        variables = {**_EMPLOYED_NO_COLLATERAL, "applicantType": "SELF_EMPLOYED"}
        inputs = _inputs(variables=variables, tool_calls=[])
        assert no_bank_statement_for_employed_applicant(inputs=inputs) is None

    def test_no_verify_employment_fails_for_self_employed(self):
        variables = {**_EMPLOYED_NO_COLLATERAL, "applicantType": "SELF_EMPLOYED"}
        calls = [_tool("Verify Employment")]
        inputs = _inputs(variables=variables, tool_calls=calls)
        assert _value(no_verify_employment_for_self_employed_applicant(inputs=inputs)) is False

    def test_no_verify_employment_none_for_employed(self):
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=[])
        assert no_verify_employment_for_self_employed_applicant(inputs=inputs) is None


class TestStepEfficiency:
    def test_pass_within_budget(self):
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, iterations=4)
        assert _value(step_efficiency(inputs=inputs)) is True

    def test_fail_over_budget(self):
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, iterations=5)
        assert _value(step_efficiency(inputs=inputs)) is False

    def test_collateral_adds_one_to_budget(self):
        variables = {**_EMPLOYED_NO_COLLATERAL, "hasCollateral": True}
        inputs = _inputs(variables=variables, iterations=5)
        assert _value(step_efficiency(inputs=inputs)) is True

    def test_collateral_still_rejects_excess_calls(self):
        variables = {**_EMPLOYED_NO_COLLATERAL, "hasCollateral": True}
        assert _value(step_efficiency(inputs=_inputs(variables=variables, iterations=6))) is False

    def test_report_explains_that_final_response_is_counted(self):
        result = step_efficiency(inputs=_inputs(variables=_EMPLOYED_NO_COLLATERAL, iterations=4))
        assert "including final response" in result.rationale

    def test_none_when_no_inference_count(self):
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL)
        assert step_efficiency(inputs=inputs) is None


class TestAffordabilityAfterIncome:
    def test_pass_when_income_first(self):
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=_full_employed_calls())
        assert _value(affordability_called_after_income_confirmed(inputs=inputs)) is True

    def test_fail_when_affordability_first(self):
        calls = [_tool("Assess Affordability"), _tool("Verify Employment")]
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=calls)
        assert _value(affordability_called_after_income_confirmed(inputs=inputs)) is False

    def test_none_when_either_missing(self):
        calls = [_tool("Verify Employment")]
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=calls)
        assert affordability_called_after_income_confirmed(inputs=inputs) is None


class TestToolArgumentCorrectness:
    def test_none_when_no_arguments_captured(self):
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=_full_employed_calls())
        assert tool_argument_correctness(inputs=inputs) is None

    def test_full_score_when_arguments_correct(self):
        inputs = _inputs(
            variables=_EMPLOYED_NO_COLLATERAL, tool_calls=_full_employed_calls(arguments=True)
        )
        assert _value(tool_argument_correctness(inputs=inputs)) == 1.0

    def test_penalised_on_wrong_argument(self):
        calls = _full_employed_calls(arguments=True)
        calls[0] = _tool("Check Credit Score", arguments={"customerId": "WRONG"})
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=calls)
        assert _value(tool_argument_correctness(inputs=inputs)) < 1.0


class TestCollateralValuationCalledCorrectly:
    def test_none_when_no_collateral(self):
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=[])
        assert collateral_valuation_called_correctly_when_required(inputs=inputs) is None

    def test_zero_when_never_called(self):
        variables = {**_EMPLOYED_NO_COLLATERAL, "hasCollateral": True}
        inputs = _inputs(variables=variables, tool_calls=[])
        assert _value(collateral_valuation_called_correctly_when_required(inputs=inputs)) == 0.0

    def test_none_when_called_but_args_uncaptured(self):
        variables = {**_EMPLOYED_NO_COLLATERAL, "hasCollateral": True}
        calls = [_tool("Value Collateral")]  # no arguments
        inputs = _inputs(variables=variables, tool_calls=calls)
        assert collateral_valuation_called_correctly_when_required(inputs=inputs) is None

    def test_full_when_correct_application_id(self):
        variables = {**_EMPLOYED_NO_COLLATERAL, "hasCollateral": True}
        calls = [_tool("Value Collateral", arguments={"applicationId": "A1"})]
        inputs = _inputs(variables=variables, tool_calls=calls)
        assert _value(collateral_valuation_called_correctly_when_required(inputs=inputs)) == 1.0

    def test_zero_on_application_id_mismatch(self):
        variables = {**_EMPLOYED_NO_COLLATERAL, "hasCollateral": True}
        calls = [_tool("Value Collateral", arguments={"applicationId": "WRONG"})]
        inputs = _inputs(variables=variables, tool_calls=calls)
        assert _value(collateral_valuation_called_correctly_when_required(inputs=inputs)) == 0.0


class TestRequestedAmountPassedToAffordability:
    def test_zero_when_never_called(self):
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=[])
        assert _value(requested_amount_passed_to_affordability(inputs=inputs)) == 0.0

    def test_none_when_args_uncaptured(self):
        calls = [_tool("Assess Affordability")]  # no arguments
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=calls)
        assert requested_amount_passed_to_affordability(inputs=inputs) is None

    def test_pass_when_arguments_match(self):
        calls = [_tool("Assess Affordability", arguments={"customerId": "C1", "requestedAmount": 5000})]
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=calls)
        assert _value(requested_amount_passed_to_affordability(inputs=inputs)) is True

    def test_fail_on_mismatch(self):
        calls = [_tool("Assess Affordability", arguments={"customerId": "C1", "requestedAmount": 999})]
        inputs = _inputs(variables=_EMPLOYED_NO_COLLATERAL, tool_calls=calls)
        assert _value(requested_amount_passed_to_affordability(inputs=inputs)) is False
