"""Build scorer inputs from an agent run's Fluxnova process variables.

The agentic subprocess records everything the scorers need in its own process
variables, so scoring never has to read prompt/response content from telemetry:

- ``_agentConversationHistory`` (JSON): every turn of the agent's conversation.
  ``ASSISTANT`` turns carry ``toolCalls`` (``toolCallId``, ``toolId``,
  ``arguments``), each matching ``TOOL`` turn carries its ``toolResult``, and
  the last non-empty ``ASSISTANT`` turn is the agent's final answer.
- ``_agentLoopIndex``: the number of LLM calls, including the final answer.
- The ``agent:context`` variables declared on the ad-hoc subprocess
  (``applicantType``, ``hasCollateral``, ...): the applicant inputs.

The functions here turn those into the canonical scorer payload
(``{"input_variables", "tool_calls", "iterations"}`` plus the final output),
the process-variable equivalent of :func:`fluxnova_mlflow_dataset.traces.scorer_inputs_from_trace`.
Every scorer in :mod:`fluxnova_mlflow_dataset.scorers` reads only that plain
shape, so it works unchanged whichever source fed it.

:func:`load_agent_run` is the one-call entry point for the eval workers: it
reads a run's variables and its deployed BPMN (for tool display names and the
``agent:context`` variable list) over the Fluxnova REST API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fluxnova_mlflow_dataset.bpmn import BpmnLookup, BpmnLookupError
from fluxnova_mlflow_dataset.fluxnova_client import FluxnovaClient

AGENT_HISTORY_VAR = "_agentConversationHistory"
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


def agent_final_output(variables: dict[str, Any]) -> str | None:
    """Return the agent's final response: the content of the last non-empty
    ``ASSISTANT`` turn in ``_agentConversationHistory``, or ``None`` if the
    history is absent, unparseable, or has no assistant reply."""
    for message in reversed(_conversation_history(variables)):
        if not isinstance(message, dict) or message.get("role") != _ASSISTANT_ROLE:
            continue
        content = (message.get("content") or "").strip()
        if content:
            return content
    return None


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
        variables: The run's process variables, containing ``_agentConversationHistory``.
        tool_names: ``{BPMN service task element id: display name}`` (e.g.
            :meth:`BpmnLookup.tool_names`). The history's ``toolId`` is the
            element id, but the scorers key on the display name.
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
    """Return total LLM calls, including the final answer; never subtract a turn."""
    return variables.get(LOOP_INDEX_VAR)


def scorer_inputs_from_variables(
    input_variables: dict[str, Any],
    run_variables: dict[str, Any],
    tool_names: dict[str, str | None],
) -> dict[str, Any]:
    """Build the scorers' canonical ``inputs`` payload from process variables.

    Args:
        input_variables: The applicant/process variables the agent ran with.
        run_variables: The run's process variables read back after completion.
        tool_names: ``{BPMN service task element id: display name}``.
    """
    return {
        "input_variables": input_variables,
        "tool_calls": tool_calls_from_variables(run_variables, tool_names),
        "iterations": iterations_from_variables(run_variables),
    }


@dataclass
class AgentRun:
    """Scorer-ready data for one agent run, read from process variables."""

    process_instance_id: str
    inputs: dict[str, Any]
    outputs: str | None


def load_agent_run(
    client: FluxnovaClient, process_instance_id: str, subprocess_id: str | None = None
) -> AgentRun:
    """Read one agent run's scorer inputs and final output from Fluxnova.

    ``process_instance_id`` is the instance the ad-hoc subprocess ran in (for a
    Call Activity, the *child* instance). The deployed BPMN is fetched to map
    tool element ids to display names and to select the ``agent:context``
    variables. ``subprocess_id`` defaults to the first ad-hoc subprocess in
    that BPMN. If the subprocess declares no ``agent:context``, every
    variable not prefixed with ``_`` is used as an input variable.
    """
    variables = client.get_variables(process_instance_id)
    lookup = BpmnLookup.from_xml(
        client.get_process_definition_xml(process_instance_id), subprocess_id
    )
    try:
        context_names = lookup.context_variable_names()
        input_variables = {name: variables[name] for name in context_names if name in variables}
    except BpmnLookupError:
        input_variables = {k: v for k, v in variables.items() if not k.startswith("_")}
    return AgentRun(
        process_instance_id=process_instance_id,
        inputs=scorer_inputs_from_variables(input_variables, variables, lookup.tool_names()),
        outputs=agent_final_output(variables),
    )


def decision_keyword(final_output: str | None) -> str | None:
    """Return ``"APPROVE"``/``"REJECT"`` when the final output's last non-empty
    line is exactly one of them, else ``None``. Lets eval records note the
    decision without storing the agent's full (sensitive) response."""
    if not final_output:
        return None
    lines = [line.strip() for line in final_output.splitlines() if line.strip()]
    last = lines[-1].strip("*`_ .").upper() if lines else ""
    return last if last in {"APPROVE", "REJECT"} else None
