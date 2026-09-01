"""Tests for ``MlflowTraceReader`` (reads spans via ``mlflow.search_traces``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from fluxnova_mlflow_dataset.traces import (
    InvokeAgentMetrics,
    MlflowTraceReader,
    ToolCallSpan,
    TraceStoreError,
)

_NS_PER_MS = 1_000_000


@dataclass
class _FakeStatus:
    name: str


@dataclass
class _FakeSpan:
    attributes: dict[str, Any]
    start_time_ns: int = 0
    end_time_ns: int = 1_000 * _NS_PER_MS
    status_code: _FakeStatus = field(default_factory=lambda: _FakeStatus("OK"))

    def get_attribute(self, key: str) -> Any:
        return self.attributes.get(key)


@dataclass
class _FakeTraceData:
    spans: list[_FakeSpan]


@dataclass
class _FakeTraceInfo:
    trace_id: str = "tr-default"


@dataclass
class _FakeTrace:
    data: _FakeTraceData
    info: _FakeTraceInfo = field(default_factory=_FakeTraceInfo)


def _span(operation_name: str, attributes: dict, **kwargs) -> _FakeSpan:
    return _FakeSpan(attributes={"gen_ai.operation.name": operation_name, **attributes}, **kwargs)


def _trace(*spans: _FakeSpan, trace_id: str = "tr-default") -> _FakeTrace:
    return _FakeTrace(data=_FakeTraceData(spans=list(spans)), info=_FakeTraceInfo(trace_id=trace_id))


def _reader(monkeypatch: pytest.MonkeyPatch, traces: list[_FakeTrace]) -> MlflowTraceReader:
    reader = MlflowTraceReader(tracking_uri="sqlite:///test.db", experiment_id="1")
    monkeypatch.setattr(reader, "_search_traces", lambda: traces)
    return reader


class TestFindCompletedRuns:
    def test_returns_conversation_id_and_agent_name_for_matching_agents(self, monkeypatch):
        traces = [
            _trace(_span("invoke_agent", {
                "gen_ai.agent.name": "AdHocSubProcess_LoanAssessmentAgent",
                "gen_ai.conversation.id": "proc-123",
            })),
            _trace(_span("invoke_agent", {
                "gen_ai.agent.name": "SomeOtherAgent",
                "gen_ai.conversation.id": "proc-999",
            })),
        ]
        reader = _reader(monkeypatch, traces)
        result = reader.find_completed_runs({"AdHocSubProcess_LoanAssessmentAgent"})
        assert result == [("proc-123", "AdHocSubProcess_LoanAssessmentAgent")]

    def test_empty_list_when_no_agent_names_match(self, monkeypatch):
        traces = [_trace(_span("invoke_agent", {
            "gen_ai.agent.name": "OtherAgent", "gen_ai.conversation.id": "proc-123",
        }))]
        reader = _reader(monkeypatch, traces)
        assert reader.find_completed_runs({"AdHocSubProcess_LoanAssessmentAgent"}) == []


class TestGetInvokeAgentMetrics:
    def test_returns_metrics_from_invoke_agent_span(self, monkeypatch):
        traces = [_trace(_span(
            "invoke_agent",
            {
                "gen_ai.agent.name": "AdHocSubProcess_LoanAssessmentAgent",
                "gen_ai.request.model": "llama3.1",
                "gen_ai.conversation.id": "proc-123",
                "gen_ai.usage.input_tokens": 100,
                "gen_ai.usage.output_tokens": 50,
                "gen_ai.invoke_agent.inference_calls": 3,
                "gen_ai.invoke_agent.tool_calls": 2,
            },
            start_time_ns=0,
            end_time_ns=2_500 * _NS_PER_MS,
        ))]
        reader = _reader(monkeypatch, traces)
        result = reader.get_invoke_agent_metrics("proc-123")

        assert result == InvokeAgentMetrics(
            agent_name="AdHocSubProcess_LoanAssessmentAgent",
            request_model="llama3.1",
            conversation_id="proc-123",
            input_tokens=100,
            output_tokens=50,
            inference_calls=3,
            tool_calls=2,
            duration_ms=2500.0,
        )

    def test_raises_when_no_matching_correlation_id(self, monkeypatch):
        traces = [_trace(_span("invoke_agent", {"gen_ai.conversation.id": "other-proc"}))]
        reader = _reader(monkeypatch, traces)
        with pytest.raises(TraceStoreError, match="No traces found"):
            reader.get_invoke_agent_metrics("proc-123")

    def test_raises_when_trace_has_no_invoke_agent_span(self, monkeypatch):
        traces = [_trace(_span("chat", {"gen_ai.conversation.id": "proc-123"}))]
        reader = _reader(monkeypatch, traces)
        with pytest.raises(TraceStoreError, match="No invoke_agent span"):
            reader.get_invoke_agent_metrics("proc-123")


class TestGetToolCallSpans:
    def test_returns_one_entry_per_execute_tool_span_in_same_trace(self, monkeypatch):
        traces = [_trace(
            _span("invoke_agent", {"gen_ai.conversation.id": "proc-123"}),
            _span("chat", {}),
            _span(
                "execute_tool",
                {
                    "gen_ai.tool.name": "Check Credit Score",
                    "gen_ai.tool.call.id": "call-1",
                    "gen_ai.agent.name": "AdHocSubProcess_LoanAssessmentAgent",
                },
                start_time_ns=0,
                end_time_ns=500 * _NS_PER_MS,
                status_code=_FakeStatus("OK"),
            ),
            _span(
                "execute_tool",
                {
                    "gen_ai.tool.name": "Assess Affordability",
                    "gen_ai.tool.call.id": "call-2",
                    "error.type": "tool_error",
                },
                start_time_ns=0,
                end_time_ns=100 * _NS_PER_MS,
                status_code=_FakeStatus("ERROR"),
            ),
        )]
        reader = _reader(monkeypatch, traces)
        result = reader.get_tool_call_spans("proc-123")

        assert result == [
            ToolCallSpan(
                tool_name="Check Credit Score",
                tool_call_id="call-1",
                agent_name="AdHocSubProcess_LoanAssessmentAgent",
                status="OK",
                error_type=None,
                duration_ms=500.0,
            ),
            ToolCallSpan(
                tool_name="Assess Affordability",
                tool_call_id="call-2",
                agent_name=None,
                status="ERROR",
                error_type="tool_error",
                duration_ms=100.0,
            ),
        ]

    def test_empty_list_when_no_tool_spans(self, monkeypatch):
        traces = [_trace(_span("invoke_agent", {"gen_ai.conversation.id": "proc-123"}))]
        reader = _reader(monkeypatch, traces)
        assert reader.get_tool_call_spans("proc-123") == []


class TestGetLlmMessages:
    def test_returns_chat_spans_ordered_by_start_time(self, monkeypatch):
        traces = [_trace(
            _span("invoke_agent", {"gen_ai.conversation.id": "proc-123"}),
            _span(
                "chat",
                {
                    "gen_ai.request.model": "llama3.1",
                    "gen_ai.input.messages": '[{"role":"USER","content":"hi"}]',
                },
                start_time_ns=2_000 * _NS_PER_MS,
            ),
            _span(
                "chat",
                {
                    "gen_ai.request.model": "llama3.1",
                    "gen_ai.input.messages": "[]",
                    "gen_ai.output.messages": "final answer text",
                },
                start_time_ns=1_000 * _NS_PER_MS,
            ),
        )]
        reader = _reader(monkeypatch, traces)
        result = reader.get_llm_messages("proc-123")

        assert [m.start_time_unix_nano for m in result] == [1_000 * _NS_PER_MS, 2_000 * _NS_PER_MS]
        assert result[0].output_messages == "final answer text"
        assert result[1].output_messages is None

    def test_empty_list_when_no_chat_spans(self, monkeypatch):
        traces = [_trace(_span("invoke_agent", {"gen_ai.conversation.id": "proc-123"}))]
        reader = _reader(monkeypatch, traces)
        assert reader.get_llm_messages("proc-123") == []


class TestGetFinalOutput:
    def test_prefers_invoke_agent_span_output_messages(self, monkeypatch):
        traces = [_trace(
            _span("invoke_agent", {
                "gen_ai.conversation.id": "proc-123",
                "gen_ai.output.messages": "APPROVE: strong credit history",
            }),
            _span(
                "chat",
                {"gen_ai.output.messages": "an earlier, less relevant chat reply"},
                start_time_ns=1_000 * _NS_PER_MS,
            ),
        )]
        reader = _reader(monkeypatch, traces)
        assert reader.get_final_output("proc-123") == "APPROVE: strong credit history"

    def test_falls_back_to_last_chat_span_when_invoke_agent_has_no_output(self, monkeypatch):
        traces = [_trace(
            _span("invoke_agent", {"gen_ai.conversation.id": "proc-123"}),
            _span(
                "chat",
                {"gen_ai.output.messages": "first reply"},
                start_time_ns=1_000 * _NS_PER_MS,
            ),
            _span(
                "chat",
                {"gen_ai.output.messages": "final reply"},
                start_time_ns=2_000 * _NS_PER_MS,
            ),
        )]
        reader = _reader(monkeypatch, traces)
        assert reader.get_final_output("proc-123") == "final reply"

    def test_returns_none_when_no_output_anywhere(self, monkeypatch):
        traces = [_trace(_span("invoke_agent", {"gen_ai.conversation.id": "proc-123"}))]
        reader = _reader(monkeypatch, traces)
        assert reader.get_final_output("proc-123") is None

    def test_raises_when_no_matching_correlation_id(self, monkeypatch):
        traces = [_trace(_span("invoke_agent", {"gen_ai.conversation.id": "other-proc"}))]
        reader = _reader(monkeypatch, traces)
        with pytest.raises(TraceStoreError, match="No traces found"):
            reader.get_final_output("proc-123")


class TestGetTraceId:
    def test_returns_trace_id_for_matching_correlation_id(self, monkeypatch):
        traces = [
            _trace(
                _span("invoke_agent", {"gen_ai.conversation.id": "proc-123"}),
                trace_id="tr-abc123",
            ),
            _trace(
                _span("invoke_agent", {"gen_ai.conversation.id": "proc-999"}),
                trace_id="tr-def456",
            ),
        ]
        reader = _reader(monkeypatch, traces)
        assert reader.get_trace_id("proc-123") == "tr-abc123"

    def test_raises_when_no_matching_correlation_id(self, monkeypatch):
        traces = [_trace(_span("invoke_agent", {"gen_ai.conversation.id": "other-proc"}))]
        reader = _reader(monkeypatch, traces)
        with pytest.raises(TraceStoreError, match="No traces found"):
            reader.get_trace_id("proc-123")


class TestWaitForTrace:
    def test_returns_immediately_when_trace_already_present(self, monkeypatch):
        traces = [_trace(_span("invoke_agent", {"gen_ai.conversation.id": "proc-123"}), trace_id="tr-1")]
        reader = _reader(monkeypatch, traces)
        result = reader.wait_for_trace("proc-123", timeout=5, poll_interval=0)
        assert result.info.trace_id == "tr-1"

    def test_retries_until_trace_arrives(self, monkeypatch):
        found = [_trace(_span("invoke_agent", {"gen_ai.conversation.id": "proc-123"}), trace_id="tr-1")]
        calls = {"n": 0}

        def _search():
            calls["n"] += 1
            return found if calls["n"] >= 3 else []

        reader = MlflowTraceReader(tracking_uri="sqlite:///test.db", experiment_id="1")
        monkeypatch.setattr(reader, "_search_traces", _search)
        monkeypatch.setattr("fluxnova_mlflow_dataset.traces.time.sleep", lambda _: None)

        result = reader.wait_for_trace("proc-123", timeout=5, poll_interval=0)

        assert result.info.trace_id == "tr-1"
        assert calls["n"] == 3

    def test_raises_after_timeout_if_trace_never_arrives(self, monkeypatch):
        reader = _reader(monkeypatch, [])
        monkeypatch.setattr("fluxnova_mlflow_dataset.traces.time.sleep", lambda _: None)
        with pytest.raises(TraceStoreError, match="No traces found"):
            reader.wait_for_trace("proc-123", timeout=0, poll_interval=0)
