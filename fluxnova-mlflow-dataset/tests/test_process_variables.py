"""Tests for :mod:`fluxnova_mlflow_dataset.process_variables`."""

from __future__ import annotations

import json

from fluxnova_mlflow_dataset.process_variables import AGENT_HISTORY_VAR, agent_final_output


def _vars(history: object) -> dict:
    return {AGENT_HISTORY_VAR: json.dumps(history) if not isinstance(history, str) else history}


def test_returns_last_assistant_message() -> None:
    history = [
        {"role": "USER", "content": "Assess this loan."},
        {"role": "ASSISTANT", "content": "Thinking..."},
        {"role": "TOOL_EXECUTION_RESULT", "content": "creditScore=700"},
        {"role": "ASSISTANT", "content": "Decision: APPROVE"},
    ]
    assert agent_final_output(_vars(history)) == "Decision: APPROVE"


def test_skips_empty_trailing_assistant_message() -> None:
    history = [
        {"role": "ASSISTANT", "content": "Real answer"},
        {"role": "ASSISTANT", "content": "   "},
        {"role": "ASSISTANT", "content": ""},
    ]
    assert agent_final_output(_vars(history)) == "Real answer"


def test_missing_variable_returns_none() -> None:
    assert agent_final_output({}) is None


def test_empty_history_returns_none() -> None:
    assert agent_final_output(_vars([])) is None


def test_no_assistant_message_returns_none() -> None:
    history = [{"role": "USER", "content": "hi"}]
    assert agent_final_output(_vars(history)) is None


def test_unparseable_history_returns_none() -> None:
    assert agent_final_output({AGENT_HISTORY_VAR: "{not valid json"}) is None


def test_non_list_history_returns_none() -> None:
    assert agent_final_output(_vars({"role": "ASSISTANT"})) is None


def test_accepts_already_parsed_list() -> None:
    history = [{"role": "ASSISTANT", "content": "parsed"}]
    assert agent_final_output({AGENT_HISTORY_VAR: history}) == "parsed"


# --- tool calls / scorer inputs / load_agent_run ---------------------------

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

from fluxnova_mlflow_dataset.bpmn import BpmnLookup, BpmnLookupError  # noqa: E402
from fluxnova_mlflow_dataset.process_variables import (  # noqa: E402
    LOOP_INDEX_VAR,
    decision_keyword,
    load_agent_run,
    tool_calls_from_variables,
)

_HISTORY = [
    {"role": "USER", "content": "Assess the applicant"},
    {
        "role": "ASSISTANT",
        "content": "",
        "toolCalls": [
            {"toolCallId": "c1", "toolId": "ServiceTask_Credit", "arguments": '{"customerId": "C1"}'},
            {"toolCallId": "c2", "toolId": "ServiceTask_Fraud", "arguments": {"applicationId": "A1"}},
        ],
    },
    {"role": "TOOL", "toolCallId": "c1", "toolResult": {"status": "OK"}},
    {"role": "TOOL", "toolCallId": "c2", "toolResult": {"status": "FAILED"}},
    {"role": "ASSISTANT", "content": "Evidence...\nAPPROVE"},
]

_BPMN = """<?xml version="1.0"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             xmlns:agent="http://fluxnova.finos.org/schema/1.0/ai/agent">
  <process id="p">
    <adHocSubProcess id="Agent">
      <extensionElements>
        <agent:config provider="openai" model="gpt-4o" systemPrompt="x"/>
        <agent:context><agent:variable name="applicantType"/><agent:variable name="hasCollateral"/></agent:context>
      </extensionElements>
      <serviceTask id="ServiceTask_Credit" name="Check Credit Score"/>
      <serviceTask id="ServiceTask_Fraud" name="Run Fraud Screening"/>
    </adHocSubProcess>
  </process>
</definitions>"""


def test_tool_calls_keep_order_status_and_arguments() -> None:
    calls = tool_calls_from_variables(
        {AGENT_HISTORY_VAR: json.dumps(_HISTORY)},
        {"ServiceTask_Credit": "Check Credit Score"},
    )
    assert calls == [
        {"name": "Check Credit Score", "status": "OK", "arguments": {"customerId": "C1"}},
        {"name": "ServiceTask_Fraud", "status": "ERROR", "arguments": {"applicationId": "A1"}},
    ]


def test_bpmn_from_xml_defaults_to_first_adhoc_subprocess() -> None:
    lookup = BpmnLookup.from_xml(_BPMN)
    assert lookup.context_variable_names() == ["applicantType", "hasCollateral"]
    assert lookup.tool_names()["ServiceTask_Fraud"] == "Run Fraud Screening"


def test_bpmn_from_xml_without_subprocess_raises() -> None:
    with pytest.raises(BpmnLookupError):
        BpmnLookup.from_xml('<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"/>')


def test_load_agent_run_reads_only_context_variables() -> None:
    client = MagicMock()
    client.get_variables.return_value = {
        AGENT_HISTORY_VAR: json.dumps(_HISTORY),
        LOOP_INDEX_VAR: 3,
        "applicantType": "EMPLOYED",
        "hasCollateral": False,
        "creditScore": 720,
    }
    client.get_process_definition_xml.return_value = _BPMN

    run = load_agent_run(client, "child-1")

    assert run.outputs == "Evidence...\nAPPROVE"
    assert run.inputs["input_variables"] == {"applicantType": "EMPLOYED", "hasCollateral": False}
    assert run.inputs["iterations"] == 3
    assert [c["name"] for c in run.inputs["tool_calls"]] == [
        "Check Credit Score",
        "Run Fraud Screening",
    ]
    client.get_variables.assert_called_once_with("child-1")


@pytest.mark.parametrize(
    "output, expected",
    [("Reasons\nAPPROVE", "APPROVE"), ("x\n**REJECT**", "REJECT"), ("I approve", None), (None, None)],
)
def test_decision_keyword(output, expected) -> None:
    assert decision_keyword(output) == expected
