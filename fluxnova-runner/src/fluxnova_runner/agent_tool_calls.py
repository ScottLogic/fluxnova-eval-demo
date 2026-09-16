"""Extract the agentic subprocess's tool-call history from process variables.

The loan-assessment agent's ``_agentConversationHistory`` process variable (see
``agent_output.py``) carries every tool call and its result inline: each
``ASSISTANT`` turn's ``toolCalls`` entries (``toolCallId``, ``toolId``,
``arguments``) and each matching ``TOOL`` turn's ``toolResult`` (keyed by the
same ``toolCallId``). This module turns that into the canonical
``{"name", "status", "arguments"}`` shape
``fluxnova_mlflow_dataset.scorers`` expects — the process-variable equivalent
of ``fluxnova_mlflow_dataset.traces.tool_calls_from_spans`` — plus the agent
loop's iteration count (``_agentLoopIndex``). Reading these via the Fluxnova
REST API rather than an MLflow trace lets a ``predict_fn`` build the full
deterministic-scorer ``inputs`` payload with no ``mlflow.*`` call — see
``agent_output.py``'s docstring for why a nested ``mlflow.search_traces``
inside a ``predict_fn`` is unsafe.
"""

from __future__ import annotations

import json
from typing import Any

from fluxnova_runner.agent_output import AGENT_HISTORY_VAR

LOOP_INDEX_VAR = "_agentLoopIndex"

_ASSISTANT_ROLE = "ASSISTANT"
_TOOL_ROLE = "TOOL"


def _conversation_history(variables: dict[str, Any]) -> list[dict[str, Any]]:
    raw = variables.get(AGENT_HISTORY_VAR)
    if not raw:
        return []
    try:
        history = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    return history if isinstance(history, list) else []


def _parsed_arguments(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _status_from_tool_result(tool_result: Any) -> str:
    status = tool_result.get("status") if isinstance(tool_result, dict) else None
    return "OK" if isinstance(status, str) and status.lower() == "ok" else "ERROR"


def tool_calls_from_variables(
    variables: dict[str, Any], tool_names: dict[str, str | None]
) -> list[dict[str, Any]]:
    """Return one ``{"name", "status", "arguments"}`` record per tool call the
    agent made, in the order it made them.

    Args:
        variables: The run's process variables (e.g. from
            :meth:`fluxnova_runner.client.Client.get_variables`), containing
            ``_agentConversationHistory``.
        tool_names: ``{BPMN service task element id: display name}`` — e.g.
            ``fluxnova_mlflow_dataset.bpmn.BpmnLookup.tool_names()``. The
            conversation history's ``toolId`` is the BPMN element id
            (``ServiceTask_...``), but the scorers key on the human-readable
            display name (``"Check Credit Score"``, etc).
    """
    history = _conversation_history(variables)
    tool_results_by_call_id = {
        message["toolCallId"]: message.get("toolResult")
        for message in history
        if message.get("role") == _TOOL_ROLE and message.get("toolCallId")
    }
    calls: list[dict[str, Any]] = []
    for message in history:
        if message.get("role") != _ASSISTANT_ROLE:
            continue
        for call in message.get("toolCalls") or []:
            call_id = call.get("toolCallId")
            tool_id = call.get("toolId")
            calls.append(
                {
                    "name": tool_names.get(tool_id, tool_id),
                    "status": _status_from_tool_result(tool_results_by_call_id.get(call_id)),
                    "arguments": _parsed_arguments(call.get("arguments")),
                }
            )
    return calls


def iterations_from_variables(variables: dict[str, Any]) -> int | None:
    """Return the agent loop's iteration count, or ``None`` if the run has none."""
    return variables.get(LOOP_INDEX_VAR)


def scorer_inputs_from_variables(
    input_variables: dict[str, Any],
    run_variables: dict[str, Any],
    tool_names: dict[str, str | None],
) -> dict[str, Any]:
    """Build the deterministic scorers' canonical ``inputs`` payload from
    process variables, with no MLflow trace read involved.

    Mirrors ``fluxnova_mlflow_dataset.traces.scorer_inputs_from_trace``'s
    output shape (``{"input_variables", "tool_calls", "iterations"}``), so
    every scorer in ``fluxnova_mlflow_dataset.scorers`` — which only ever reads
    that plain dict shape — works unchanged whether it's fed from a trace or
    from a live run's process variables.

    Args:
        input_variables: The applicant/process variables the run was started
            with (i.e. what was passed to ``Client.start_process``).
        run_variables: The run's process variables read back after completion
            (i.e. ``Client.get_variables(instance_id)``).
        tool_names: ``{BPMN service task element id: display name}``.
    """
    return {
        "input_variables": input_variables,
        "tool_calls": tool_calls_from_variables(run_variables, tool_names),
        "iterations": iterations_from_variables(run_variables),
    }
