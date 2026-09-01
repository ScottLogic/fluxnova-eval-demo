"""Tests for ``score_process_instance`` (mocks MLflow + trace-reader boundaries)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from eval_service_worker import scoring


@dataclass
class _FakeExperiment:
    experiment_id: str = "1"


@dataclass
class _FakeScorer:
    """Stands in for both ``decision_quality_judge(...)`` and the deterministic
    scorer functions — only ``.name`` is used by ``score_process_instance``."""

    name: str


class _FakeTraceReader:
    def __init__(self, tracking_uri: str, experiment_id: str) -> None:
        self.tracking_uri = tracking_uri
        self.experiment_id = experiment_id

    def get_final_output(self, process_instance_id: str) -> str | None:
        return _OUTPUTS.get(process_instance_id)

    def get_trace(self, process_instance_id: str):
        return f"trace-for-{process_instance_id}"

    def wait_for_trace(self, process_instance_id: str, timeout: float, poll_interval: float):
        return self.get_trace(process_instance_id)



class _FakeRow:
    """Stands in for a ``pandas.Series`` row of ``result.tables['eval_results']``."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class _RowOnlyTable:
    def __init__(self, row: _FakeRow) -> None:
        self.iloc = [row]


class _FakeEvaluateResult:
    def __init__(self, row: _FakeRow) -> None:
        # `.iloc[0]` is all `score_process_instance` needs from the table.
        self.tables = {"eval_results": _RowOnlyTable(row)}


_OUTPUTS: dict[str, str | None] = {}

_DETERMINISTIC_ROW_DEFAULTS = {
    "required_tools_called/value": True,
    "required_tools_called/rationale": "All expected tools were called.",
    "no_tool_errors/value": True,
    "no_tool_errors/rationale": "No tool call errors.",
    "definitive_decision_stated/value": True,
    "definitive_decision_stated/rationale": "Final output states a definitive decision.",
}


def _stub_common(
    monkeypatch: pytest.MonkeyPatch, decision_quality_value: str, decision_quality_rationale: str
) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    monkeypatch.setattr(
        scoring.mlflow, "set_tracking_uri", lambda uri: calls.setdefault("tracking_uri", uri)
    )
    monkeypatch.setattr(
        scoring.mlflow,
        "set_experiment",
        lambda name: (calls.setdefault("experiment_name", name), _FakeExperiment())[1],
    )
    monkeypatch.setattr(scoring, "MlflowTraceReader", _FakeTraceReader)
    monkeypatch.setattr(
        scoring, "decision_quality_judge", lambda model: _FakeScorer(name="decision_quality")
    )
    monkeypatch.setattr(
        scoring,
        "DETERMINISTIC_SCORERS",
        [
            _FakeScorer(name="required_tools_called"),
            _FakeScorer(name="no_tool_errors"),
            _FakeScorer(name="definitive_decision_stated"),
        ],
    )

    row = _FakeRow(
        {
            "decision_quality/value": decision_quality_value,
            "decision_quality/rationale": decision_quality_rationale,
            **_DETERMINISTIC_ROW_DEFAULTS,
        }
    )
    fake_result = _FakeEvaluateResult(row)

    def _fake_evaluate(*, data, scorers):
        calls["evaluate_data"] = data
        calls["evaluate_scorers"] = scorers
        return fake_result

    monkeypatch.setattr(scoring.mlflow.genai, "evaluate", _fake_evaluate)
    monkeypatch.setattr(
        scoring,
        "write_to_mlflow_dataset",
        lambda **kwargs: calls.setdefault("dataset_kwargs", kwargs),
    )
    return calls


class TestScoreProcessInstance:
    def test_passes_when_judge_says_yes(self, monkeypatch):
        _OUTPUTS["proc-1"] = "APPROVE: strong credit history"
        calls = _stub_common(monkeypatch, "yes", "Looks good.")

        outcome = scoring.score_process_instance(
            "proc-1",
            tracking_uri="http://localhost:5000",
            process_key="loanAssessmentEvalProcess",
            experiment_name=None,
            judge_model="gateway:/fluxnova-judge",
        )

        assert outcome.eval_passed is True
        assert outcome.eval_rationale == "Looks good."
        assert outcome.final_output == "APPROVE: strong credit history"
        assert outcome.scorer_results["decision_quality"]["value"] == "yes"
        assert outcome.scorer_results["required_tools_called"]["value"] is True
        assert outcome.scorer_results["no_tool_errors"]["value"] is True
        assert outcome.scorer_results["definitive_decision_stated"]["value"] is True

        # Scores against the real trace object, not a synthesized one.
        assert calls["evaluate_data"] == [{"trace": "trace-for-proc-1"}]
        assert [s.name for s in calls["evaluate_scorers"]] == [
            "decision_quality",
            "required_tools_called",
            "no_tool_errors",
            "definitive_decision_stated",
        ]

        tags = calls["dataset_kwargs"]["record"]["tags"]
        assert tags["processInstanceId"] == "proc-1"
        assert tags["decision_quality"] == "yes"
        assert tags["required_tools_called"] == "True"
        assert tags["no_tool_errors"] == "True"
        assert tags["definitive_decision_stated"] == "True"

    def test_fails_when_judge_says_no(self, monkeypatch):
        _OUTPUTS["proc-2"] = "REJECT: insufficient income"
        calls = _stub_common(monkeypatch, "no", "Missing justification.")

        outcome = scoring.score_process_instance(
            "proc-2",
            tracking_uri="http://localhost:5000",
            process_key="loanAssessmentEvalProcess",
            experiment_name=None,
            judge_model="gateway:/fluxnova-judge",
        )

        assert outcome.eval_passed is False
        assert calls["dataset_kwargs"]["record"]["tags"]["decision_quality"] == "no"

    def test_judge_value_comparison_is_case_insensitive(self, monkeypatch):
        _OUTPUTS["proc-3"] = "APPROVE"
        _stub_common(monkeypatch, "YES", "ok")

        outcome = scoring.score_process_instance(
            "proc-3",
            tracking_uri="http://localhost:5000",
            process_key="loanAssessmentEvalProcess",
            experiment_name=None,
            judge_model="gateway:/fluxnova-judge",
        )

        assert outcome.eval_passed is True

    def test_raises_no_final_output_error_when_run_has_no_output_yet(self, monkeypatch):
        _OUTPUTS["proc-4"] = None
        _stub_common(monkeypatch, "yes", "n/a")

        with pytest.raises(scoring.NoFinalOutputError, match="proc-4"):
            scoring.score_process_instance(
                "proc-4",
                tracking_uri="http://localhost:5000",
                process_key="loanAssessmentEvalProcess",
                experiment_name=None,
                judge_model="gateway:/fluxnova-judge",
            )
