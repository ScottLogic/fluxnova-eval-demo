"""Tests for :func:`fluxnova_runner.agent_output.agent_final_output`."""

from __future__ import annotations

import json

from fluxnova_runner.agent_output import AGENT_HISTORY_VAR, agent_final_output


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
