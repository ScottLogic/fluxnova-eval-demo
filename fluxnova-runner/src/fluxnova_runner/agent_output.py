"""Extract the agentic subprocess's final response from its process variables.

The loan-assessment agent records its whole conversation into the
``_agentConversationHistory`` process variable (a JSON string). The agent's
final response is the last non-empty ``ASSISTANT`` turn in that history — the
same text the agentic-subprocess plugin also exports onto the run's MLflow
trace (see ``fluxnova_mlflow_dataset.traces.final_output_from_spans``).

Reading it straight off the process variables (via the Fluxnova REST API)
rather than the MLflow trace lets callers get the agent's output without any
MLflow calls — important inside an ``mlflow.genai.evaluate`` ``predict_fn``,
where a nested ``mlflow.search_traces`` would corrupt the active trace context.
"""

from __future__ import annotations

import json
from typing import Any

AGENT_HISTORY_VAR = "_agentConversationHistory"

_ASSISTANT_ROLE = "ASSISTANT"


def agent_final_output(variables: dict[str, Any]) -> str | None:
    """Return the agent's final response text from a run's process variables.

    Args:
        variables: The process instance's variables (e.g. from
            :meth:`fluxnova_runner.client.Client.get_variables`).

    Returns:
        The content of the last non-empty ``ASSISTANT`` message in
        ``_agentConversationHistory``, or ``None`` if the history is absent,
        unparseable, or contains no assistant reply.
    """
    raw = variables.get(AGENT_HISTORY_VAR)
    if not raw:
        return None
    try:
        history = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(history, list):
        return None
    for message in reversed(history):
        if not isinstance(message, dict):
            continue
        if message.get("role") != _ASSISTANT_ROLE:
            continue
        content = (message.get("content") or "").strip()
        if content:
            return content
    return None
