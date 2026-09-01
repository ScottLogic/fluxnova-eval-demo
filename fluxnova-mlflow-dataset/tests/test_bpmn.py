"""Tests for ``fluxnova_mlflow_dataset.bpmn`` against the real loan-assessment BPMN fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from fluxnova_mlflow_dataset.bpmn import BpmnLookup, BpmnLookupError

_BPMN_PATH = Path(__file__).resolve().parent.parent.parent / "bpmn" / "loan-assesment.bpmn"
_SUBPROCESS_ID = "AdHocSubProcess_LoanAssessmentAgent"


@pytest.fixture
def lookup() -> BpmnLookup:
    return BpmnLookup(_BPMN_PATH, _SUBPROCESS_ID)


def test_system_prompt_returns_configured_prompt(lookup: BpmnLookup) -> None:
    prompt = lookup.system_prompt()
    assert prompt.startswith("You are a senior loan assessment analyst.")
    assert "Run Fraud Screening" in prompt


def test_context_variable_names_returns_full_list(lookup: BpmnLookup) -> None:
    names = lookup.context_variable_names()
    assert "customerId" in names
    assert "applicantType" in names
    assert "hasCollateral" in names
    assert len(names) == 17


def test_tool_input_output_params_for_multi_param_task(lookup: BpmnLookup) -> None:
    params = lookup.tool_input_output_params("ServiceTask_FraudScreening")
    assert params.input_params == ["applicationId", "customerId"]
    assert params.output_params == ["fraudRiskScore"]


def test_tool_input_output_params_for_affordability_task(lookup: BpmnLookup) -> None:
    params = lookup.tool_input_output_params("ServiceTask_AffordabilityAssessment")
    assert params.input_params == ["customerId", "requestedAmount"]
    assert params.output_params == ["debtToIncomeRatio", "affordabilityPassed"]


def test_tool_input_output_params_unknown_activity_raises(lookup: BpmnLookup) -> None:
    with pytest.raises(BpmnLookupError, match="ServiceTask_DoesNotExist"):
        lookup.tool_input_output_params("ServiceTask_DoesNotExist")


def test_tool_names_maps_element_id_to_display_name(lookup: BpmnLookup) -> None:
    names = lookup.tool_names()
    assert names["ServiceTask_FraudScreening"] == "Run Fraud Screening"
    assert names["ServiceTask_CreditScoreCheck"] == "Check Credit Score"
    assert names["ServiceTask_CollateralValuation"] == "Value Collateral"


def test_unknown_subprocess_id_raises() -> None:
    lookup = BpmnLookup(_BPMN_PATH, "NotARealSubprocess")
    with pytest.raises(BpmnLookupError, match="NotARealSubprocess"):
        lookup.system_prompt()
