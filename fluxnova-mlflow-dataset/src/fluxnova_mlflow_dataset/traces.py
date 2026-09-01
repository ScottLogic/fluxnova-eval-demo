"""Reads GenAI span data straight out of MLflow's own trace store.

Replaces the previous ``fluxnova_listener`` design (a bespoke local OTLP/HTTP
receiver + JSON-lines span store) now that the OTel Collector can export
traces directly to MLflow's native OTLP endpoint (``/v1/traces``) and
``mlflow.search_traces`` can read them straight back — no separate trace
transport/storage layer needed on our side. See ``proposal.md`` for the
rationale and GENAI_SEMCONV_ALIGNMENT.md for the span/attribute shapes this
reads (``gen_ai.*`` semantic-convention attributes on ``invoke_agent``,
``execute_tool`` and ``chat`` spans).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import mlflow

# Attribute set on every span by ``AgentOtelTracing`` — see
# GENAI_SEMCONV_ALIGNMENT.md's "Source -> signal mapping" table.
_OP_NAME_ATTR = "gen_ai.operation.name"
_CONVERSATION_ID_ATTR = "gen_ai.conversation.id"
_INVOKE_AGENT_OP = "invoke_agent"
_EXECUTE_TOOL_OP = "execute_tool"
_CHAT_OP = "chat"

_DEFAULT_MAX_RESULTS = 5000


class TraceStoreError(Exception):
    """Raised when MLflow's trace store has no data (or incomplete data) for a run."""


@dataclass
class InvokeAgentMetrics:
    """Data read off the ``invoke_agent`` span for one subprocess execution."""

    agent_name: str | None
    request_model: str | None
    conversation_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    inference_calls: int | None
    tool_calls: int | None
    duration_ms: float | None


@dataclass
class ToolCallSpan:
    """Data read off one ``execute_tool`` child span."""

    tool_name: str | None
    tool_call_id: str | None
    agent_name: str | None
    status: str
    error_type: str | None
    duration_ms: float | None


@dataclass
class ChatMessages:
    """Input/output message content read off one ``chat`` span, in call order."""

    model: str | None
    input_messages: str | None
    output_messages: str | None
    start_time_unix_nano: int


class MlflowTraceReader:
    """Reads GenAI spans for completed agent runs out of an MLflow experiment's traces.

    Args:
        tracking_uri: The MLflow tracking URI traces were exported into (the
                      same store the OTel Collector's ``otlphttp`` exporter
                      points at).
        experiment_id: Only traces logged against this experiment are considered.
        max_results: Upper bound on how many traces to pull per query.
    """

    def __init__(
        self,
        tracking_uri: str,
        experiment_id: str,
        max_results: int = _DEFAULT_MAX_RESULTS,
    ) -> None:
        self._tracking_uri = tracking_uri
        self._experiment_id = experiment_id
        self._max_results = max_results
        self._traces_cache: list[Any] | None = None

    def find_completed_runs(self, agent_names: set[str]) -> list[tuple[str, str]]:
        """Return ``(conversation_id, agent_name)`` for every ``invoke_agent`` span
        across the experiment's traces whose ``gen_ai.agent.name`` is in ``agent_names``.

        A span only ever appears once its subprocess has ended (spans are
        exported/appended on span-end), so presence here already means
        "completed" — no separate polling of the Fluxnova engine is needed
        to detect completion.
        """
        runs: list[tuple[str, str]] = []
        for span in self._all_spans():
            if span.get_attribute(_OP_NAME_ATTR) != _INVOKE_AGENT_OP:
                continue
            agent_name = span.get_attribute("gen_ai.agent.name")
            conversation_id = span.get_attribute(_CONVERSATION_ID_ATTR)
            if agent_name in agent_names and conversation_id:
                runs.append((conversation_id, agent_name))
        return runs

    def get_invoke_agent_metrics(self, correlation_id: str) -> InvokeAgentMetrics:
        """Return iteration/tool-call counts, tokens, and duration for one run.

        Args:
            correlation_id: The process instance id — matches ``gen_ai.conversation.id``
                             on the run's ``invoke_agent`` span.
        """
        spans = self._spans_for_correlation_id(correlation_id)
        span = _find_span(spans, operation_name=_INVOKE_AGENT_OP)
        if span is None:
            raise TraceStoreError(
                f"No invoke_agent span found for correlation id '{correlation_id}'"
            )
        return InvokeAgentMetrics(
            agent_name=span.get_attribute("gen_ai.agent.name"),
            request_model=span.get_attribute("gen_ai.request.model"),
            conversation_id=span.get_attribute(_CONVERSATION_ID_ATTR),
            input_tokens=span.get_attribute("gen_ai.usage.input_tokens"),
            output_tokens=span.get_attribute("gen_ai.usage.output_tokens"),
            inference_calls=span.get_attribute("gen_ai.invoke_agent.inference_calls"),
            tool_calls=span.get_attribute("gen_ai.invoke_agent.tool_calls"),
            duration_ms=_duration_ms(span),
        )

    def get_tool_call_spans(self, correlation_id: str) -> list[ToolCallSpan]:
        """Return one ``ToolCallSpan`` per ``execute_tool`` child span for the run."""
        spans = self._spans_for_correlation_id(correlation_id)
        return tool_calls_from_spans(spans)

    def get_llm_messages(self, correlation_id: str) -> list[ChatMessages]:
        """Return each ``chat`` span's input/output messages, ordered by call time."""
        spans = self._spans_for_correlation_id(correlation_id)
        chat_spans = sorted(
            (s for s in spans if s.get_attribute(_OP_NAME_ATTR) == _CHAT_OP),
            key=lambda s: s.start_time_ns or 0,
        )
        return [
            ChatMessages(
                model=span.get_attribute("gen_ai.request.model"),
                input_messages=span.get_attribute("gen_ai.input.messages"),
                output_messages=span.get_attribute("gen_ai.output.messages"),
                start_time_unix_nano=span.start_time_ns or 0,
            )
            for span in chat_spans
        ]

    def get_final_output(self, correlation_id: str) -> str | None:
        """Return the agent's final output text for one run, reading trace data only.

        Deliberately reads nothing beyond MLflow's trace store (no BPMN file, no
        Fluxnova REST API) — callers needing goal/input-variables/tool-call detail
        too should use :func:`fluxnova_mlflow_dataset.report.build_agent_report`
        instead.
        """
        spans = self._spans_for_correlation_id(correlation_id)
        return final_output_from_spans(spans)

    def get_input_variables(self, correlation_id: str) -> dict[str, Any]:
        """Return the applicant/process input variables the agent itself received.

        Read off the ``invoke_agent`` span's ``mlflow.spanInputs`` attribute (the
        same ``agent:context`` variables wired up in the BPMN's ad-hoc subprocess,
        e.g. ``applicantType``/``hasCollateral``/``requestedAmount``) — this is
        trace data, not a BPMN/Fluxnova REST read, so profile-conditional
        deterministic scorers (see ``scorers.py``) can stay trace-only too.
        """
        spans = self._spans_for_correlation_id(correlation_id)
        return input_variables_from_spans(spans)

    def get_trace(self, correlation_id: str) -> Any:
        """Return the MLflow ``Trace`` object containing this run's spans.

        Useful for callers that pass a trace straight into
        ``mlflow.genai.evaluate(data=[{"trace": trace}], ...)`` so assessments
        and the resulting Evaluation Run are logged against the *same* trace.
        """
        for trace in self._search_traces():
            if any(
                span.get_attribute(_CONVERSATION_ID_ATTR) == correlation_id
                for span in trace.data.spans
            ):
                return trace
        raise TraceStoreError(
            f"No traces found for correlation id '{correlation_id}' in experiment "
            f"{self._experiment_id}. Has the collector delivered this run's traces "
            "to MLflow yet?"
        )

    def wait_for_trace(
        self,
        correlation_id: str,
        timeout: float = 30.0,
        poll_interval: float = 3.0,
    ) -> Any:
        """Like :meth:`get_trace`, but retries for up to ``timeout`` seconds if no
        trace is found yet.

        The OTel Collector delivers a completed subprocess run's spans to MLflow
        asynchronously — there's a short (usually a few seconds) window right
        after the subprocess ends where a caller (e.g. the eval-service-worker's
        BPMN service task, which runs immediately after) can be scored before the
        trace has actually landed. Polling here closes that race without relying
        on the caller's own retry/backoff (e.g. Camunda external-task retries).
        """
        deadline = time.monotonic() + timeout
        while True:
            try:
                return self.get_trace(correlation_id)
            except TraceStoreError:
                if time.monotonic() >= deadline:
                    raise
                self._traces_cache = None  # force a fresh search on the next attempt
                time.sleep(poll_interval)

    def get_trace_id(self, correlation_id: str) -> str:
        """Return the MLflow trace id (``tr-...``) containing this run's spans.

        Needed to attach assessments via ``mlflow.log_feedback(trace_id=...)``
        after reading the run's data purely by ``gen_ai.conversation.id``.
        """
        return self.get_trace(correlation_id).info.trace_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _spans_for_correlation_id(self, correlation_id: str) -> list[Any]:
        """Return every span in any trace containing a span tagged with this correlation id."""
        matching_traces = [
            trace
            for trace in self._search_traces()
            if any(
                span.get_attribute(_CONVERSATION_ID_ATTR) == correlation_id
                for span in trace.data.spans
            )
        ]
        if not matching_traces:
            raise TraceStoreError(
                f"No traces found for correlation id '{correlation_id}' in experiment "
                f"{self._experiment_id}. Has the collector delivered this run's traces "
                "to MLflow yet?"
            )
        return [span for trace in matching_traces for span in trace.data.spans]

    def _all_spans(self) -> list[Any]:
        return [span for trace in self._search_traces() for span in trace.data.spans]

    def _search_traces(self) -> list[Any]:
        if self._traces_cache is None:
            mlflow.set_tracking_uri(self._tracking_uri)
            self._traces_cache = mlflow.search_traces(
                experiment_ids=[self._experiment_id],
                max_results=self._max_results,
                return_type="list",
            )
        return self._traces_cache


def _status_str(span: Any) -> str:
    status_code = getattr(span, "status_code", None)
    name = getattr(status_code, "name", status_code)
    return "OK" if name == "OK" else "ERROR"


def _duration_ms(span: Any) -> float | None:
    start = getattr(span, "start_time_ns", None)
    end = getattr(span, "end_time_ns", None)
    if start is None or end is None:
        return None
    return (end - start) / 1e6


def _last_output_message(chat_spans_by_time: list[Any]) -> str | None:
    """Return the most recent ``chat`` span's output message, if any."""
    for span in reversed(chat_spans_by_time):
        output = span.get_attribute("gen_ai.output.messages")
        if output is not None:
            return output
    return None


def _find_span(spans: list[Any], operation_name: str) -> Any | None:
    for span in spans:
        if span.get_attribute(_OP_NAME_ATTR) == operation_name:
            return span
    return None


def final_output_from_spans(spans: list[Any]) -> str | None:
    """Return the agent's final output text given a run's spans.

    Prefers the ``invoke_agent`` span's own ``gen_ai.output.messages`` attribute
    (set by the ``agentic-subprocess`` plugin at subprocess end, when content
    capture is enabled — see GENAI_SEMCONV_ALIGNMENT.md). Falls back to the last
    ``chat`` child span's output message for traces recorded before that
    attribute existed on ``invoke_agent``.

    A free function (not a ``MlflowTraceReader`` method) so it can be reused both
    by the reader itself and by trace-based custom scorers in ``scorers.py``,
    which only ever have a raw ``trace.data.spans`` list to work with.
    """
    invoke_agent_span = _find_span(spans, operation_name=_INVOKE_AGENT_OP)
    if invoke_agent_span is not None:
        output = invoke_agent_span.get_attribute("gen_ai.output.messages")
        if output is not None:
            return output
    return _last_output_message(
        sorted(
            (s for s in spans if s.get_attribute(_OP_NAME_ATTR) == _CHAT_OP),
            key=lambda s: s.start_time_ns or 0,
        )
    )


def input_variables_from_spans(spans: list[Any]) -> dict[str, Any]:
    """Return the applicant/process input variables given a run's spans.

    Read off the ``invoke_agent`` span's ``mlflow.spanInputs`` attribute — the
    same ``agent:context`` variables (``applicantType``, ``hasCollateral``,
    ``requestedAmount``, etc.) wired up in the BPMN's ad-hoc subprocess. A free
    function for the same reuse reason as :func:`final_output_from_spans`.
    """
    invoke_agent_span = _find_span(spans, operation_name=_INVOKE_AGENT_OP)
    if invoke_agent_span is None:
        return {}
    raw = invoke_agent_span.get_attribute("mlflow.spanInputs")
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    return dict(raw)


def tool_calls_from_spans(spans: list[Any]) -> list[ToolCallSpan]:
    """Return one ``ToolCallSpan`` per ``execute_tool`` span, given a run's spans."""
    return [
        ToolCallSpan(
            tool_name=span.get_attribute("gen_ai.tool.name"),
            tool_call_id=span.get_attribute("gen_ai.tool.call.id"),
            agent_name=span.get_attribute("gen_ai.agent.name"),
            status=_status_str(span),
            error_type=span.get_attribute("error.type"),
            duration_ms=_duration_ms(span),
        )
        for span in spans
        if span.get_attribute(_OP_NAME_ATTR) == _EXECUTE_TOOL_OP
    ]
