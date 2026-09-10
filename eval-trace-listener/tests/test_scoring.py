from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from _fakes import make_trace

from eval_trace_listener import scoring
from eval_trace_listener.scoring import ScoringError, score_trace


class _FakeScorer:
    def __init__(self, name: str) -> None:
        self.name = name


def _patch_evaluate(monkeypatch, row: dict) -> list:
    """Patch mlflow.genai.evaluate to return a one-row eval_results table."""
    captured: list = []

    def fake_evaluate(*, data, scorers):
        captured.append((data, scorers))
        table = pd.DataFrame([row])
        return SimpleNamespace(tables={"eval_results": table})

    monkeypatch.setattr(scoring.mlflow.genai, "evaluate", fake_evaluate)
    return captured


def test_score_trace_all_pass(monkeypatch) -> None:
    scorers = [_FakeScorer("required_tools_called"), _FakeScorer("no_tool_errors")]
    _patch_evaluate(
        monkeypatch,
        {
            "required_tools_called/value": True,
            "required_tools_called/rationale": "ok",
            "no_tool_errors/value": True,
            "no_tool_errors/rationale": "ok",
        },
    )
    outcome = score_trace(make_trace("tr-1"), scorers)
    assert outcome.trace_id == "tr-1"
    assert outcome.passed is True
    assert set(outcome.scorer_results) == {"required_tools_called", "no_tool_errors"}


def test_score_trace_one_fail(monkeypatch) -> None:
    scorers = [_FakeScorer("required_tools_called"), _FakeScorer("no_tool_errors")]
    _patch_evaluate(
        monkeypatch,
        {
            "required_tools_called/value": True,
            "required_tools_called/rationale": "ok",
            "no_tool_errors/value": False,
            "no_tool_errors/rationale": "tool failed",
        },
    )
    outcome = score_trace(make_trace("tr-2"), scorers)
    assert outcome.passed is False
    assert "no_tool_errors=False" in outcome.summary()


def test_score_trace_handles_stringified_bool(monkeypatch) -> None:
    scorers = [_FakeScorer("required_tools_called")]
    _patch_evaluate(
        monkeypatch,
        {"required_tools_called/value": "true", "required_tools_called/rationale": "ok"},
    )
    outcome = score_trace(make_trace("tr-3"), scorers)
    assert outcome.passed is True


def test_score_trace_passes_trace_to_evaluate(monkeypatch) -> None:
    scorers = [_FakeScorer("required_tools_called")]
    captured = _patch_evaluate(
        monkeypatch,
        {"required_tools_called/value": True, "required_tools_called/rationale": "ok"},
    )
    trace = make_trace("tr-4")
    score_trace(trace, scorers)
    (data, used_scorers), = captured
    [row] = data
    assert row["trace"] is trace
    assert row["inputs"] == {"input_variables": {}, "tool_calls": [], "iterations": None}
    assert "outputs" in row
    assert used_scorers is scorers


def test_score_trace_raises_scoring_error_when_no_eval_results(monkeypatch) -> None:
    # MLflow couldn't fetch the trace's span data (RESOURCE_DOES_NOT_EXIST), so it
    # returns a result with no eval_results table — must raise ScoringError, not KeyError.
    def fake_evaluate(*, data, scorers):
        return SimpleNamespace(tables={})

    monkeypatch.setattr(scoring.mlflow.genai, "evaluate", fake_evaluate)
    with pytest.raises(ScoringError):
        score_trace(make_trace("tr-missing"), [_FakeScorer("required_tools_called")])


def test_listener_scorers_bundle_includes_llm_judges() -> None:
    # The default bundle score_trace/TraceListener use must be the deterministic
    # checks plus the two trace-derivable LLM judges — and must NOT include
    # matches_golden (which needs a golden expected_output a bare trace lacks).
    names = {s.name for s in scoring.LISTENER_SCORERS}
    assert {"decision_quality", "evidence_citation"} <= names
    assert "required_tools_called" in names
    assert "matches_golden" not in names


def test_score_trace_defaults_to_listener_scorers(monkeypatch) -> None:
    # Called with no explicit scorers, score_trace runs the full LISTENER_SCORERS bundle.
    captured = _patch_evaluate(
        monkeypatch,
        {s.name + "/value": True for s in scoring.LISTENER_SCORERS}
        | {s.name + "/rationale": "ok" for s in scoring.LISTENER_SCORERS},
    )
    score_trace(make_trace("tr-default"))
    (_data, used_scorers), = captured
    assert used_scorers is scoring.LISTENER_SCORERS


def test_score_trace_raises_scoring_error_on_empty_eval_results(monkeypatch) -> None:
    def fake_evaluate(*, data, scorers):
        return SimpleNamespace(tables={"eval_results": pd.DataFrame()})

    monkeypatch.setattr(scoring.mlflow.genai, "evaluate", fake_evaluate)
    with pytest.raises(ScoringError):
        score_trace(make_trace("tr-empty"), [_FakeScorer("required_tools_called")])
