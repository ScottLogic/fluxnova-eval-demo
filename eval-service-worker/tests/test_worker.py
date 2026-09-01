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


class TestMakeHandler:
    def test_retries_on_no_final_output_error(self, monkeypatch):
        monkeypatch.setattr(
            worker,
            "score_process_instance",
            MagicMock(side_effect=NoFinalOutputError("no output yet")),
        )
        handler = worker.make_handler(EvalServiceConfig())
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
        handler = worker.make_handler(EvalServiceConfig())
        task = _task()

        handler(task)

        task.failure.assert_called_once()
        _, kwargs = task.failure.call_args
        assert kwargs["max_retries"] == worker._MAX_RETRIES

    def test_unexpected_error_is_not_retried(self, monkeypatch):
        monkeypatch.setattr(
            worker, "score_process_instance", MagicMock(side_effect=ValueError("boom"))
        )
        handler = worker.make_handler(EvalServiceConfig())
        task = _task()

        handler(task)

        task.failure.assert_called_once()
        _, kwargs = task.failure.call_args
        assert kwargs["max_retries"] == 0

    def test_completes_task_on_success(self, monkeypatch):
        outcome = MagicMock(eval_passed=True, eval_rationale="Looks good.")
        monkeypatch.setattr(
            worker, "score_process_instance", MagicMock(return_value=outcome)
        )
        handler = worker.make_handler(EvalServiceConfig())
        task = _task()

        handler(task)

        task.complete.assert_called_once()
        _, kwargs = task.complete.call_args
        assert kwargs["global_variables"]["evalPassed"]["value"] is True


if __name__ == "__main__":
    pytest.main([__file__])
