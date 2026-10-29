"""Tests for ``make_handler`` — the external-task handler's error routing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fluxnova_mlflow_dataset import TraceStoreError

from eval_service_worker import worker
from eval_service_worker.config import EvalServiceConfig
from eval_service_worker.scoring import NoFinalOutputError


def _task(process_instance_id: str = "proc-1") -> MagicMock:
    task = MagicMock()
    task.get_process_instance_id.return_value = process_instance_id
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
        outcome = MagicMock(eval_passed=True, eval_rationale="Looks good.")
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
        outcome = MagicMock(eval_passed=True, eval_rationale="ok")
        score = MagicMock(return_value=outcome)
        monkeypatch.setattr(worker, "score_process_instance", score)
        handler = worker.make_handler(EvalServiceConfig(), _client(child_id="child-9"))

        handler(_task(process_instance_id="parent-1"))

        scored_id = score.call_args[0][0]
        assert scored_id == "child-9"

    def test_falls_back_to_parent_when_no_child(self, monkeypatch):
        outcome = MagicMock(eval_passed=True, eval_rationale="ok")
        score = MagicMock(return_value=outcome)
        monkeypatch.setattr(worker, "score_process_instance", score)
        handler = worker.make_handler(EvalServiceConfig(), _client(child_id=None))

        handler(_task(process_instance_id="parent-1"))

        assert score.call_args[0][0] == "parent-1"

    def test_falls_back_to_parent_when_lookup_errors(self, monkeypatch):
        from fluxnova_mlflow_dataset import ApiError

        outcome = MagicMock(eval_passed=True, eval_rationale="ok")
        score = MagicMock(return_value=outcome)
        monkeypatch.setattr(worker, "score_process_instance", score)
        client = MagicMock()
        client.get_child_instance_id.side_effect = ApiError("boom")
        handler = worker.make_handler(EvalServiceConfig(), client)

        handler(_task(process_instance_id="parent-1"))

        assert score.call_args[0][0] == "parent-1"


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
