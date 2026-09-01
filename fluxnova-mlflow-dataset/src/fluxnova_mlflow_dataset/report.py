"""Builds the agent-history report from MLflow trace + BPMN + core-API sources."""

from __future__ import annotations

import json
from typing import Any, Protocol

from fluxnova_mlflow_dataset.bpmn import BpmnLookup
from fluxnova_mlflow_dataset.traces import ChatMessages, InvokeAgentMetrics, ToolCallSpan


class VariableReader(Protocol):
    """Anything that can look up a completed instance's final variables (e.g. ``FluxnovaClient``)."""

    def get_variables(self, instance_id: str) -> dict[str, Any]: ...


class TraceReader(Protocol):
    """Anything that can read GenAI span data for a run (e.g. ``MlflowTraceReader``)."""

    def get_invoke_agent_metrics(self, correlation_id: str) -> InvokeAgentMetrics: ...

    def get_tool_call_spans(self, correlation_id: str) -> list[ToolCallSpan]: ...

    def get_llm_messages(self, correlation_id: str) -> list[ChatMessages]: ...


def build_agent_report(
    client: VariableReader,
    bpmn: BpmnLookup,
    traces: TraceReader,
    instance_id: str,
    variable_names: list[str],
) -> dict[str, Any]:
    """Compose an ``/agent-history``-shaped report for one process instance.

    Args:
        variable_names: The process variable names to include in
            ``inputVariables`` (e.g. a workflow config's ``variables`` keys).
    """
    variables = client.get_variables(instance_id)
    input_variables = {name: variables[name] for name in variable_names if name in variables}

    metrics = traces.get_invoke_agent_metrics(instance_id)
    tool_spans = traces.get_tool_call_spans(instance_id)
    element_id_by_tool_name = {name: element_id for element_id, name in bpmn.tool_names().items()}

    tool_calls = [
        _build_tool_call(span, bpmn, variables, element_id_by_tool_name) for span in tool_spans
    ]

    final_output = _last_output_message(traces.get_llm_messages(instance_id))

    return {
        "processInstanceId": instance_id,
        "goal": bpmn.system_prompt(),
        "finalOutput": final_output,
        "iterations": metrics.inference_calls,
        "inputVariables": input_variables,
        "toolCalls": tool_calls,
        "model": metrics.request_model,
        "totalPromptTokens": metrics.input_tokens,
        "totalCompletionTokens": metrics.output_tokens,
        "executionTime": metrics.duration_ms,
    }


def _build_tool_call(
    span: Any,
    bpmn: BpmnLookup,
    variables: dict[str, Any],
    element_id_by_tool_name: dict[str, str],
) -> dict[str, Any]:
    """Build one ``toolCalls[]`` entry from a tool-call span + BPMN/variable data."""
    element_id = element_id_by_tool_name.get(span.tool_name) if span.tool_name else None
    tool_input: dict[str, Any] = {}
    if element_id is not None:
        params = bpmn.tool_input_output_params(element_id)
        tool_input = {name: variables.get(name) for name in params.input_params}
    return {
        "toolName": span.tool_name,
        "toolElementId": element_id,
        "toolCallId": span.tool_call_id,
        "toolInput": json.dumps(tool_input),
        "status": "COMPLETED" if span.status == "OK" else "FAILED",
        "durationMs": span.duration_ms,
    }


def _last_output_message(messages: list[Any]) -> str | None:
    """Return the most recent ``chat`` span's output text, if any."""
    for message in reversed(messages):
        if message.output_messages is not None:
            return message.output_messages
    return None
