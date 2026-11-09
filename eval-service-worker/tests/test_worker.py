"""Tests for ``make_handler`` — the external-task handler's error routing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fluxnova_mlflow_dataset import TraceStoreError

from eval_service_worker import worker
from eval_service_worker.config import EvalServiceConfig
from eval_service_worker.scoring import NoFinalOutputError


def _task(process_instance_id: str = "proc-1", variables: dict | None = None) -> MagicMock:
    task = MagicMock()
    task.get_process_instance_id.return_value = process_instance_id
    task.get_variable.side_effect = (variables or {}).get
    return task


def _client(child_id: str | None = None) -> MagicMock:
    client = MagicMock()
    client.get_child_instance_id.return_value = child_id
    return client


class TestMakeHandler:
    def test_retries_on_no_final_output_error(self, monkeypatch):
        monkeypatch.setattr(
            worker,
            "score_process_instance",
            MagicMock(side_effect=NoFinalOutputError("no output yet")),
        )
        handler = worker.make_handler(EvalServiceConfig(), _client())
        task = _task()

        handler(task)

        task.failure.assert_called_once()
        _, kwargs = task.failure.call_args
        assert kwargs["max_retries"] == worker._MAX_RETRIES

    def test_retries_on_trace_store_error(self, monkeypatch):
        """A TraceStoreError (trace not delivered to MLflow yet, even after the
        internal poll in score_process_instance) should also be retried at the
        Camunda level, not treated as a permanent failure."""
        monkeypatch.setattr(
            worker,
            "score_process_instance",
            MagicMock(side_effect=TraceStoreError("No traces found for correlation id 'proc-1'")),
        )
        handler = worker.make_handler(EvalServiceConfig(), _client())
        task = _task()

        handler(task)

        task.failure.assert_called_once()
        _, kwargs = task.failure.call_args
        assert kwargs["max_retries"] == worker._MAX_RETRIES

    def test_retries_when_process_variables_cannot_be_read(self, monkeypatch):
        from fluxnova_mlflow_dataset import ApiError

        monkeypatch.setattr(
            worker, "score_process_instance", MagicMock(side_effect=ApiError("HTTP 503"))
        )
        task = _task()

        worker.make_handler(EvalServiceConfig(), _client())(task)

        assert task.failure.call_args.kwargs["max_retries"] == worker._MAX_RETRIES

    def test_passes_fluxnova_client_to_scoring(self, monkeypatch):
        score = MagicMock(return_value=MagicMock(eval_passed=True, eval_rationale="ok", eval_score=1.0, failed_scorers=()))
        monkeypatch.setattr(worker, "score_process_instance", score)
        client = _client(child_id="child-9")

        worker.make_handler(EvalServiceConfig(), client)(_task())

        assert score.call_args.kwargs["client"] is client

    def test_unexpected_error_is_not_retried(self, monkeypatch):
        monkeypatch.setattr(
            worker, "score_process_instance", MagicMock(side_effect=ValueError("boom"))
        )
        handler = worker.make_handler(EvalServiceConfig(), _client())
        task = _task()

        handler(task)

        task.failure.assert_called_once()
        _, kwargs = task.failure.call_args
        assert kwargs["max_retries"] == 0

    def test_completes_task_on_success(self, monkeypatch):
        outcome = MagicMock(eval_passed=True, eval_rationale="Looks good.", eval_score=1.0, failed_scorers=())
        score = MagicMock(return_value=outcome)
        monkeypatch.setattr(worker, "score_process_instance", score)
        handler = worker.make_handler(EvalServiceConfig(), _client())
        task = _task()

        handler(task)

        task.complete.assert_called_once()
        _, kwargs = task.complete.call_args
        assert kwargs["global_variables"]["evalPassed"]["value"] is True

    def test_scores_child_instance_when_present(self, monkeypatch):
        """When the parent (eval) instance has a Call Activity child, scoring
        must target the child's instance id, not the parent's."""
        outcome = MagicMock(eval_passed=True, eval_rationale="ok", eval_score=1.0, failed_scorers=())
        score = MagicMock(return_value=outcome)
        monkeypatch.setattr(worker, "score_process_instance", score)
        handler = worker.make_handler(EvalServiceConfig(), _client(child_id="child-9"))

        handler(_task(process_instance_id="parent-1"))

        scored_id = score.call_args[0][0]
        assert scored_id == "child-9"

    def test_falls_back_to_parent_when_no_child(self, monkeypatch):
        outcome = MagicMock(eval_passed=True, eval_rationale="ok", eval_score=1.0, failed_scorers=())
        score = MagicMock(return_value=outcome)
        monkeypatch.setattr(worker, "score_process_instance", score)
        handler = worker.make_handler(EvalServiceConfig(), _client(child_id=None))

        handler(_task(process_instance_id="parent-1"))

        assert score.call_args[0][0] == "parent-1"

    def test_falls_back_to_parent_when_lookup_errors(self, monkeypatch):
        from fluxnova_mlflow_dataset import ApiError

        outcome = MagicMock(eval_passed=True, eval_rationale="ok", eval_score=1.0, failed_scorers=())
        score = MagicMock(return_value=outcome)
        monkeypatch.setattr(worker, "score_process_instance", score)
        client = MagicMock()
        client.get_child_instance_id.side_effect = ApiError("boom")
        handler = worker.make_handler(EvalServiceConfig(), client)

        handler(_task(process_instance_id="parent-1"))

        assert score.call_args[0][0] == "parent-1"


class TestGuardrailThresholds:
    def _outcome(self) -> MagicMock:
        return MagicMock(
            eval_passed=True,
            eval_rationale="ok",
            eval_score=0.9,
            failed_scorers=("step_efficiency",),
        )

    def test_passes_bpmn_thresholds_to_scoring_and_returns_score(self, monkeypatch):
        score = MagicMock(return_value=self._outcome())
        monkeypatch.setattr(worker, "score_process_instance", score)
        task = _task(variables={"evalMinScore": 0.8, "evalRequiredScorers": "decision_quality"})

        worker.make_handler(EvalServiceConfig(), _client())(task)

        thresholds = score.call_args.kwargs["thresholds"]
        assert thresholds.min_score == 0.8
        assert thresholds.required_scorers == ("decision_quality",)
        variables = task.complete.call_args.kwargs["global_variables"]
        assert variables["evalScore"] == {"value": 0.9, "type": "Double"}
        assert variables["evalFailedScorers"]["value"] == "step_efficiency"

    def test_defaults_when_bpmn_sets_no_thresholds(self, monkeypatch):
        score = MagicMock(return_value=self._outcome())
        monkeypatch.setattr(worker, "score_process_instance", score)

        worker.make_handler(EvalServiceConfig(), _client())(_task())

        thresholds = score.call_args.kwargs["thresholds"]
        assert thresholds.min_score == 1.0
        assert thresholds.required_scorers == ()

    @pytest.mark.parametrize(
        "variables",
        [
            {"evalMinScore": "high"},
            {"evalMinScore": 1.5},
            {"evalRequiredScorers": "decision_quality,not_a_scorer"},
        ],
    )
    def test_invalid_thresholds_raise_incident_without_scoring(self, monkeypatch, variables):
        score = MagicMock()
        monkeypatch.setattr(worker, "score_process_instance", score)
        task = _task(variables=variables)

        worker.make_handler(EvalServiceConfig(), _client())(task)

        score.assert_not_called()
        assert task.failure.call_args.kwargs["max_retries"] == 0


class TestReviewRouting:
    def _outcome(self, passed: bool) -> MagicMock:
        return MagicMock(eval_passed=passed, eval_rationale="r", eval_score=1.0, failed_scorers=())

    def _run(self, monkeypatch, *, passed=True, variables=None, roll=0.0, run_number=None):
        score = MagicMock(return_value=self._outcome(passed))
        monkeypatch.setattr(worker, "score_process_instance", score)
        client = _client()
        client.get_run_number.return_value = run_number
        task = _task(process_instance_id="parent-1", variables=variables)
        worker.make_handler(EvalServiceConfig(), client, rng=lambda: roll)(task)
        completed = task.complete.call_args.kwargs.get("global_variables", {}) if task.complete.called else None
        values = {k: v["value"] for k, v in (completed or {}).items()}
        return score, client, task, values

    def test_failed_eval_requires_review(self, monkeypatch):
        _, client, _, values = self._run(monkeypatch, passed=False)
        assert values["reviewRequired"] is True
        assert values["reviewReason"] == "FAILED_EVAL"
        assert values["evalSampled"] is True
        client.get_run_number.assert_not_called()  # every-Nth is off by default

    def test_passed_eval_needs_no_review(self, monkeypatch):
        _, _, _, values = self._run(monkeypatch, passed=True)
        assert values["reviewRequired"] is False
        assert values["reviewReason"] == ""

    def test_unsampled_run_is_completed_without_scoring(self, monkeypatch):
        score, _, task, values = self._run(
            monkeypatch, variables={"evalSampleRate": 0.25}, roll=0.5
        )
        score.assert_not_called()
        assert values == {"evalSampled": False, "reviewRequired": False, "reviewReason": ""}

    def test_sampled_run_is_scored(self, monkeypatch):
        score, _, _, values = self._run(monkeypatch, variables={"evalSampleRate": 0.25}, roll=0.1)
        score.assert_called_once()
        assert values["evalSampled"] is True

    def test_every_nth_run_is_forced_to_review_even_when_passing(self, monkeypatch):
        _, client, _, values = self._run(
            monkeypatch, passed=True, variables={"forceReviewEveryN": 5}, run_number=10
        )
        client.get_run_number.assert_called_once_with("parent-1")
        assert values["reviewRequired"] is True
        assert values["reviewReason"] == "FORCED_EVERY_N"
        assert values["runNumber"] == 10

    def test_forced_run_is_scored_even_when_outside_the_sample(self, monkeypatch):
        score, _, _, values = self._run(
            monkeypatch,
            passed=False,
            variables={"forceReviewEveryN": 3, "evalSampleRate": 0.0},
            roll=0.99,
            run_number=9,
        )
        score.assert_called_once()
        assert values["reviewReason"] == "FAILED_EVAL,FORCED_EVERY_N"

    def test_other_runs_are_not_forced(self, monkeypatch):
        _, _, _, values = self._run(
            monkeypatch, passed=True, variables={"forceReviewEveryN": 5}, run_number=11
        )
        assert values["reviewRequired"] is False
        assert values["runNumber"] == 11

    def test_run_number_lookup_failure_is_retried(self, monkeypatch):
        from fluxnova_mlflow_dataset import ApiError

        score = MagicMock()
        monkeypatch.setattr(worker, "score_process_instance", score)
        client = _client()
        client.get_run_number.side_effect = ApiError("HTTP 503")
        task = _task(variables={"forceReviewEveryN": 2})
        worker.make_handler(EvalServiceConfig(), client)(task)
        score.assert_not_called()
        assert task.failure.call_args.kwargs["max_retries"] == worker._MAX_RETRIES

    @pytest.mark.parametrize(
        "variables",
        [{"evalSampleRate": 2}, {"forceReviewEveryN": -1}, {"forceReviewEveryN": 2.5}, {"forceReviewEveryN": "x"}],
    )
    def test_invalid_review_policy_raises_incident(self, monkeypatch, variables):
        score, _, task, _ = self._run(monkeypatch, variables=variables)
        score.assert_not_called()
        assert task.failure.call_args.kwargs["max_retries"] == 0


def test_idle_long_poll_is_not_the_ten_minute_task_lease(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(worker, "ExternalTaskWorker", factory)
    monkeypatch.setattr(worker, "FluxnovaClient", MagicMock())
    monkeypatch.setattr(worker.threading, "Thread", MagicMock())
    worker.run(EvalServiceConfig(lock_duration_ms=600_000))
    settings = factory.call_args.kwargs["config"]
    assert settings["lockDuration"] == 600_000
    assert settings["asyncResponseTimeout"] == 10_000


if __name__ == "__main__":
    pytest.main([__file__])
