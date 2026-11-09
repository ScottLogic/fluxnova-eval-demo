"""Tests for ``AsyncEvalWorker`` — the async Eval external-task handler."""

from __future__ import annotations

from unittest.mock import MagicMock

from fluxnova_mlflow_dataset import ApiError, TraceStoreError

from eval_trace_listener import worker
from eval_trace_listener.config import ListenerConfig
from eval_trace_listener.control import SampleRateControl
from eval_trace_listener.scoring import ScoringError, TraceEvalOutcome


def _task(instance_id: str = "parent-1") -> MagicMock:
    task = MagicMock()
    task.get_process_instance_id.return_value = instance_id
    return task


def _worker(child_id: str | None = "child-1", rate: float = 1.0) -> worker.AsyncEvalWorker:
    client = MagicMock()
    client.get_child_instance_id.return_value = child_id
    w = worker.AsyncEvalWorker(
        ListenerConfig(), client=client, scorers=[], sample_rate=SampleRateControl(rate)
    )
    w._fetch_trace = MagicMock(return_value="trace")
    w._score = MagicMock(
        return_value=TraceEvalOutcome(trace_id="tr-1", passed=False, scorer_results={})
    )
    return w


def test_scores_child_trace_and_completes_without_variables() -> None:
    """Even a failing score must complete with no variables: the async branch
    shares the process scope with the guardrail branch and must not route it."""
    w = _worker()
    task = _task()

    w.handle(task)

    w._fetch_trace.assert_called_once_with("child-1")
    w._score.assert_called_once_with("trace")
    task.complete.assert_called_once_with()
    task.failure.assert_not_called()


def test_falls_back_to_parent_when_no_child() -> None:
    w = _worker(child_id=None)
    w.handle(_task("parent-1"))
    w._fetch_trace.assert_called_once_with("parent-1")


def test_falls_back_to_parent_when_lookup_errors() -> None:
    w = _worker()
    w._client.get_child_instance_id.side_effect = ApiError("boom")
    w.handle(_task("parent-1"))
    w._fetch_trace.assert_called_once_with("parent-1")


def test_unsampled_task_completes_without_scoring() -> None:
    w = _worker(rate=0.0)
    task = _task()

    w.handle(task)

    w._fetch_trace.assert_not_called()
    w._score.assert_not_called()
    task.complete.assert_called_once_with()


def test_sample_rate_change_applies_live() -> None:
    w = _worker(rate=0.0)
    w._sample_rate.set(1.0)
    w.handle(_task())
    w._score.assert_called_once()


def test_trace_not_ready_is_retried() -> None:
    w = _worker()
    w._fetch_trace.side_effect = TraceStoreError("not landed")
    task = _task()

    w.handle(task)

    task.complete.assert_not_called()
    assert task.failure.call_args.kwargs["max_retries"] == worker._MAX_RETRIES


def test_scoring_error_is_retried() -> None:
    w = _worker()
    w._score.side_effect = ScoringError("no eval_results")
    task = _task()

    w.handle(task)

    assert task.failure.call_args.kwargs["max_retries"] == worker._MAX_RETRIES


def test_unexpected_error_is_not_retried() -> None:
    w = _worker()
    w._score.side_effect = ValueError("boom")
    task = _task()

    w.handle(task)

    assert task.failure.call_args.kwargs["max_retries"] == 0


def test_run_forever_subscribes_to_async_topic(monkeypatch) -> None:
    factory = MagicMock()
    thread_factory = MagicMock()
    monkeypatch.setattr(worker, "ExternalTaskWorker", factory)
    monkeypatch.setattr(worker.threading, "Thread", thread_factory)

    w = worker.AsyncEvalWorker(ListenerConfig(), client=MagicMock())
    w.run_forever(username="demo", password="demo")

    settings = factory.call_args.kwargs["config"]
    assert settings["lockDuration"] == 600_000
    assert settings["auth_basic"] == {"username": "demo", "password": "demo"}
    topics, handler = thread_factory.call_args.kwargs["args"]
    assert topics == ["agent-output-eval-async"]
    assert handler == w.handle
