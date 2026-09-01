"""Tests for ``fluxnova_mlflow_dataset.report.build_agent_report``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from fluxnova_mlflow_dataset.bpmn import BpmnLookup
from fluxnova_mlflow_dataset.fluxnova_client import FluxnovaClient
from fluxnova_mlflow_dataset.report import build_agent_report
from fluxnova_mlflow_dataset.traces import ChatMessages, InvokeAgentMetrics, ToolCallSpan

_BPMN_PATH = Path(__file__).resolve().parent.parent.parent / "bpmn" / "loan-assesment.bpmn"
_SUBPROCESS_ID = "AdHocSubProcess_LoanAssessmentAgent"

_VARIABLE_NAMES = [
    "applicationId",
    "customerId",
    "applicantName",
    "requestedAmount",
    "applicantType",
    "hasCollateral",
]


@pytest.fixture
def bpmn() -> BpmnLookup:
    return BpmnLookup(_BPMN_PATH, _SUBPROCESS_ID)


@pytest.fixture
def traces() -> Mock:
    """A fake ``MlflowTraceReader`` (duck-typed via the ``TraceReader`` protocol)."""
    mock = Mock()
    mock.get_invoke_agent_metrics.return_value = InvokeAgentMetrics(
        agent_name=_SUBPROCESS_ID,
        request_model="llama3.1",
        conversation_id="proc-123",
        input_tokens=1220,
        output_tokens=61,
        inference_calls=2,
        tool_calls=1,
        duration_ms=82284.0,
    )
    mock.get_tool_call_spans.return_value = [
        ToolCallSpan(
            tool_name="Run Fraud Screening",
            tool_call_id="call-1",
            agent_name=_SUBPROCESS_ID,
            status="OK",
            error_type=None,
            duration_ms=503.0,
        ),
    ]
    mock.get_llm_messages.return_value = [
        ChatMessages(
            model="llama3.1",
            input_messages="[]",
            output_messages="APPROVE — all checks passed.",
            start_time_unix_nano=600_000_000,
        ),
    ]
    return mock


@pytest.fixture
def client() -> Mock:
    mock = Mock(spec=FluxnovaClient)
    mock.get_variables.return_value = {
        "applicationId": "APP-001",
        "customerId": "C001",
        "applicantName": "Jane Smith",
        "requestedAmount": 50000,
        "applicantType": "EMPLOYED",
        "hasCollateral": False,
        # Tool-output variables — must NOT leak into inputVariables.
        "fraudRiskScore": 12,
    }
    return mock


def test_build_agent_report_shape(client: Mock, bpmn: BpmnLookup, traces: Mock) -> None:
    report = build_agent_report(client, bpmn, traces, "proc-123", _VARIABLE_NAMES)

    assert report["processInstanceId"] == "proc-123"
    assert report["goal"].startswith("You are a senior loan assessment analyst.")
    assert report["finalOutput"] == "APPROVE — all checks passed."
    assert report["iterations"] == 2
    assert report["model"] == "llama3.1"
    assert report["totalPromptTokens"] == 1220
    assert report["totalCompletionTokens"] == 61
    assert report["executionTime"] == 82284.0


def test_input_variables_excludes_tool_outputs(client: Mock, bpmn: BpmnLookup, traces: Mock) -> None:
    report = build_agent_report(client, bpmn, traces, "proc-123", _VARIABLE_NAMES)

    assert report["inputVariables"] == {
        "applicationId": "APP-001",
        "customerId": "C001",
        "applicantName": "Jane Smith",
        "requestedAmount": 50000,
        "applicantType": "EMPLOYED",
        "hasCollateral": False,
    }
    assert "fraudRiskScore" not in report["inputVariables"]


def test_tool_calls_resolve_element_id_and_input(client: Mock, bpmn: BpmnLookup, traces: Mock) -> None:
    report = build_agent_report(client, bpmn, traces, "proc-123", _VARIABLE_NAMES)

    assert len(report["toolCalls"]) == 1
    call = report["toolCalls"][0]
    assert call["toolName"] == "Run Fraud Screening"
    assert call["toolElementId"] == "ServiceTask_FraudScreening"
    assert call["toolCallId"] == "call-1"
    assert call["status"] == "COMPLETED"
    assert call["durationMs"] == 503.0
    assert json.loads(call["toolInput"]) == {
        "applicationId": "APP-001",
        "customerId": "C001",
    }


def test_client_get_variables_called_with_instance_id(client: Mock, bpmn: BpmnLookup, traces: Mock) -> None:
    build_agent_report(client, bpmn, traces, "proc-123", _VARIABLE_NAMES)
    client.get_variables.assert_called_once_with("proc-123")
