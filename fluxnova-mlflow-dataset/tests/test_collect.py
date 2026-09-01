"""Tests for ``fluxnova_mlflow_dataset.collect.collect_new_runs`` (the on-demand
replacement for the old ``fluxnova_listener`` polling loop).
"""

from __future__ import annotations

from unittest.mock import Mock, patch

from fluxnova_mlflow_dataset.collect import collect_new_runs
from fluxnova_mlflow_dataset.traces import ChatMessages, InvokeAgentMetrics, ToolCallSpan

_SUBPROCESS_ID = "AdHocSubProcess_LoanAssessmentAgent"


def _fake_traces() -> Mock:
    mock = Mock()
    mock.find_completed_runs.return_value = [("proc-123", _SUBPROCESS_ID)]
    mock.get_invoke_agent_metrics.return_value = InvokeAgentMetrics(
        agent_name=_SUBPROCESS_ID,
        request_model="llama3.1",
        conversation_id="proc-123",
        input_tokens=100,
        output_tokens=50,
        inference_calls=2,
        tool_calls=1,
        duration_ms=1000.0,
    )
    mock.get_tool_call_spans.return_value = [
        ToolCallSpan(
            tool_name="Check Credit Score",
            tool_call_id="call-1",
            agent_name=_SUBPROCESS_ID,
            status="OK",
            error_type=None,
            duration_ms=100.0,
        ),
    ]
    mock.get_llm_messages.return_value = [
        ChatMessages(model="llama3.1", input_messages="[]", output_messages="APPROVE", start_time_unix_nano=0),
    ]
    return mock


def _fake_client() -> Mock:
    mock = Mock()
    mock.get_variables.return_value = {"applicantType": "EMPLOYED", "hasCollateral": False}
    return mock


def _fake_bpmn() -> Mock:
    mock = Mock()
    mock.system_prompt.return_value = "You are a senior loan assessment analyst."
    mock.tool_names.return_value = {"ServiceTask_CreditScoreCheck": "Check Credit Score"}
    mock.tool_input_output_params.return_value = Mock(input_params=[], output_params=[])
    return mock


@patch("fluxnova_mlflow_dataset.collect.write_to_mlflow_dataset")
@patch("fluxnova_mlflow_dataset.collect.mlflow")
def test_collect_new_runs_writes_one_record_per_completed_run(mock_mlflow, mock_write):
    mock_mlflow.set_experiment.return_value = Mock(experiment_id="1")
    mock_write.return_value = ("fluxnova-loanAssessmentProcess", "rec-1", True)

    results = collect_new_runs(
        tracking_uri="sqlite:///test.db",
        fluxnova_url="http://localhost:8080/engine-rest",
        process_key="loanAssessmentProcess",
        subprocess_id=_SUBPROCESS_ID,
        bpmn_path="unused.bpmn",
        variable_names=["applicantType", "hasCollateral"],
        available_tools={"ServiceTask_CreditScoreCheck": "Check Credit Score"},
        expected_tool_rules=[],
        dataset_path=None,
        trace_reader=_fake_traces(),
        fluxnova_client=_fake_client(),
        bpmn=_fake_bpmn(),
    )

    assert len(results) == 1
    assert results[0].process_instance_id == "proc-123"
    assert results[0].dataset_name == "fluxnova-loanAssessmentProcess"
    assert results[0].record_id == "rec-1"
    assert results[0].written is True
    mock_write.assert_called_once()


@patch("fluxnova_mlflow_dataset.collect.write_to_mlflow_dataset")
@patch("fluxnova_mlflow_dataset.collect.mlflow")
def test_collect_new_runs_returns_empty_when_no_completed_runs(mock_mlflow, mock_write):
    mock_mlflow.set_experiment.return_value = Mock(experiment_id="1")
    traces = _fake_traces()
    traces.find_completed_runs.return_value = []

    results = collect_new_runs(
        tracking_uri="sqlite:///test.db",
        fluxnova_url="http://localhost:8080/engine-rest",
        process_key="loanAssessmentProcess",
        subprocess_id=_SUBPROCESS_ID,
        bpmn_path="unused.bpmn",
        variable_names=["applicantType"],
        available_tools={},
        expected_tool_rules=[],
        dataset_path=None,
        trace_reader=traces,
        fluxnova_client=_fake_client(),
        bpmn=_fake_bpmn(),
    )

    assert results == []
    mock_write.assert_not_called()
