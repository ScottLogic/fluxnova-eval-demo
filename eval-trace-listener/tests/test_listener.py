from __future__ import annotations

from _fakes import make_trace

from eval_trace_listener import listener as listener_mod
from eval_trace_listener.config import ListenerConfig
from eval_trace_listener.listener import _MAX_SCORING_ATTEMPTS, TraceListener
from eval_trace_listener.scoring import ScoringError, TraceEvalOutcome


class _FakeScorer:
    def __init__(self, name: str) -> None:
        self.name = name


_SCORERS = [_FakeScorer("required_tools_called"), _FakeScorer("no_tool_errors")]
_TARGET_AGENT = "AdHocSubProcess_LoanAssessmentAgent"


def _listener(**overrides):
    config = ListenerConfig(**{"agent_names": [_TARGET_AGENT], **overrides})
    listener = TraceListener(config, scorers=_SCORERS)
    calls: list[str] = []

    def fake_score(trace):
        calls.append(trace.info.trace_id)
        return TraceEvalOutcome(trace_id=trace.info.trace_id, passed=True, scorer_results={})

    listener._score = fake_score  # type: ignore[method-assign]
    return listener, calls


def test_scores_in_scope_complete_unscored_trace() -> None:
    listener, calls = _listener()
    assert listener._process_trace(make_trace("tr-1", agent_name=_TARGET_AGENT)) is True
    assert calls == ["tr-1"]


def test_skips_out_of_scope_agent() -> None:
    listener, calls = _listener()
    assert listener._process_trace(make_trace("tr-1", agent_name="SomeOtherAgent")) is False
    assert calls == []


def test_skips_incomplete_trace_without_invoke_agent_span() -> None:
    listener, calls = _listener()
    assert listener._process_trace(make_trace("tr-1", agent_name=None)) is False
    assert calls == []


def test_skips_and_remembers_already_scored_trace() -> None:
    listener, calls = _listener()
    trace = make_trace("tr-1", agent_name=_TARGET_AGENT, assessments=["required_tools_called"])
    assert listener._process_trace(trace) is False
    assert calls == []
    assert "tr-1" in listener._scored  # cached so it isn't re-inspected next poll


def test_does_not_rescore_same_trace_twice() -> None:
    listener, calls = _listener()
    trace = make_trace("tr-1", agent_name=_TARGET_AGENT)
    assert listener._process_trace(trace) is True
    assert listener._process_trace(trace) is False
    assert calls == ["tr-1"]


def test_empty_agent_names_scores_every_agent() -> None:
    listener, calls = _listener(agent_names=[])
    assert listener._process_trace(make_trace("tr-1", agent_name="AnyAgent")) is True
    assert calls == ["tr-1"]


def test_run_once_counts_only_newly_scored(monkeypatch) -> None:
    # run_once now points MLflow at the tracking store itself — stub those global
    # calls so the unit test never touches a real server.
    monkeypatch.setattr(listener_mod.mlflow, "set_tracking_uri", lambda *a, **k: None)
    monkeypatch.setattr(listener_mod.mlflow, "set_experiment", lambda *a, **k: None)
    listener, calls = _listener()
    listener._resolve_experiment_id = lambda: "1"  # type: ignore[method-assign]
    traces = [
        make_trace("tr-1", agent_name=_TARGET_AGENT),
        make_trace("tr-2", agent_name="OtherAgent"),
        make_trace("tr-3", agent_name=_TARGET_AGENT, assessments=["no_tool_errors"]),
        make_trace("tr-4", agent_name=None),
    ]
    listener._recent_traces = lambda experiment_id: traces  # type: ignore[method-assign]
    assert listener.run_once() == 1
    assert calls == ["tr-1"]


def test_run_once_returns_zero_when_experiment_missing(monkeypatch) -> None:
    monkeypatch.setattr(listener_mod.mlflow, "set_tracking_uri", lambda *a, **k: None)
    listener, calls = _listener()
    listener._resolve_experiment_id = lambda: None  # type: ignore[method-assign]
    assert listener.run_once() == 0
    assert calls == []


def test_run_once_isolates_unscoreable_trace(monkeypatch) -> None:
    # A trace that raises ScoringError must not abort the cycle: the in-scope trace
    # behind it still gets scored.
    monkeypatch.setattr(listener_mod.mlflow, "set_tracking_uri", lambda *a, **k: None)
    monkeypatch.setattr(listener_mod.mlflow, "set_experiment", lambda *a, **k: None)
    listener, calls = _listener()
    listener._resolve_experiment_id = lambda: "1"  # type: ignore[method-assign]

    def flaky_score(trace):
        if trace.info.trace_id == "tr-bad":
            raise ScoringError("trace data unavailable")
        calls.append(trace.info.trace_id)
        return TraceEvalOutcome(trace_id=trace.info.trace_id, passed=True, scorer_results={})

    listener._score = flaky_score  # type: ignore[method-assign]
    traces = [
        make_trace("tr-bad", agent_name=_TARGET_AGENT),
        make_trace("tr-good", agent_name=_TARGET_AGENT),
    ]
    listener._recent_traces = lambda experiment_id: traces  # type: ignore[method-assign]

    assert listener.run_once() == 1
    assert calls == ["tr-good"]
    assert listener._failures.get("tr-bad") == 1


def test_gives_up_on_poison_trace_after_max_attempts(monkeypatch) -> None:
    monkeypatch.setattr(listener_mod.mlflow, "set_tracking_uri", lambda *a, **k: None)
    monkeypatch.setattr(listener_mod.mlflow, "set_experiment", lambda *a, **k: None)
    listener, _calls = _listener()
    listener._resolve_experiment_id = lambda: "1"  # type: ignore[method-assign]

    def always_fail(trace):
        raise ScoringError("trace data unavailable")

    listener._score = always_fail  # type: ignore[method-assign]
    listener._recent_traces = lambda experiment_id: [  # type: ignore[method-assign]
        make_trace("tr-bad", agent_name=_TARGET_AGENT)
    ]

    for _ in range(_MAX_SCORING_ATTEMPTS):
        assert listener.run_once() == 0
    # After the retry budget it's marked scored (skipped) and no longer retried.
    assert "tr-bad" in listener._scored
    assert "tr-bad" not in listener._failures
