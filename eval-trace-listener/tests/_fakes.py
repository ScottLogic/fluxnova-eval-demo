"""Shared test fakes: lightweight stand-ins for MLflow span/trace objects.

The deterministic scorers and the listener only touch a small slice of MLflow's
span/trace API (`span.get_attribute`, `trace.data.spans`, `trace.info.*`), so a
few tiny fakes are enough to exercise them without a live MLflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class FakeSpan:
    def __init__(self, attributes: dict[str, Any]) -> None:
        self._attributes = attributes

    def get_attribute(self, key: str) -> Any:
        return self._attributes.get(key)


@dataclass
class FakeAssessment:
    name: str


@dataclass
class FakeSpanData:
    spans: list[FakeSpan]


@dataclass
class FakeTraceInfo:
    trace_id: str
    assessments: list[FakeAssessment] = field(default_factory=list)


@dataclass
class FakeTrace:
    info: FakeTraceInfo
    data: FakeSpanData


def make_trace(
    trace_id: str,
    *,
    agent_name: str | None = "AdHocSubProcess_LoanAssessmentAgent",
    assessments: list[str] | None = None,
) -> FakeTrace:
    """Build a fake trace. ``agent_name=None`` produces a trace with no
    invoke_agent span (an incomplete/non-agent run).
    """
    spans: list[FakeSpan] = []
    if agent_name is not None:
        spans.append(
            FakeSpan(
                {
                    "gen_ai.operation.name": "invoke_agent",
                    "gen_ai.agent.name": agent_name,
                }
            )
        )
    return FakeTrace(
        info=FakeTraceInfo(
            trace_id=trace_id,
            assessments=[FakeAssessment(n) for n in (assessments or [])],
        ),
        data=FakeSpanData(spans=spans),
    )
