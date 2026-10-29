from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from regression.check_review_route import (
    REVIEW_TASK,
    check_review_route,
    require_stopped_worker,
)


def _response(payload=None, *, status=200, text=""):
    return SimpleNamespace(ok=status < 400, status_code=status, text=text,
                           content=b"json" if payload is not None else b"", json=lambda: payload)


def _task(owner="eval-service-worker"):
    return {"id": "task", "processInstanceId": "parent", "workerId": owner,
            "topicName": "agent-output-eval", "activityId": "ServiceTask_EvaluateAgentOutput",
            "processDefinitionKey": "loanAssessmentEvalProcess"}


@pytest.mark.parametrize("owner", [None, "eval-service-worker", "local-route-validation"])
def test_known_orphaned_lock_is_reclaimed_and_review_verified(owner):
    responses = [_response([]), _response([_task(owner)])]
    if owner:
        responses.append(_response())
    responses += [_response(), _response(), _response([{"taskDefinitionKey": REVIEW_TASK}])]
    session = Mock(request=Mock(side_effect=responses))
    stopped = Mock()
    result = check_review_route(session, "http://engine/engine-rest", "parent", ensure_worker_stopped=stopped)
    assert result["status"] == "passed"
    stopped.assert_called_once()
    writes = [call.args[1] for call in session.request.call_args_list if call.args[0] == "POST"]
    assert writes == (["http://engine/engine-rest/external-task/task/unlock"] if owner else []) + [
        "http://engine/engine-rest/external-task/task/lock", "http://engine/engine-rest/external-task/task/complete"]


def test_running_worker_blocks_mutation():
    session = Mock(request=Mock(return_value=_response([])))
    with pytest.raises(RuntimeError, match="stop worker"):
        check_review_route(session, "http://engine", "parent", ensure_worker_stopped=Mock(side_effect=RuntimeError("stop worker")))
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)


def test_unknown_owner_is_not_unlocked():
    session = Mock(request=Mock(side_effect=[_response([]), _response([_task("another-worker")])]))
    with pytest.raises(RuntimeError, match="unrelated worker"):
        check_review_route(session, "http://engine", "parent", ensure_worker_stopped=Mock())
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)


def test_wrong_process_is_never_modified():
    task = {**_task(), "processInstanceId": "another-parent"}
    session = Mock(request=Mock(side_effect=[_response([]), _response([task])]))
    with pytest.raises(RuntimeError, match="unrelated process"):
        check_review_route(session, "http://engine", "parent", ensure_worker_stopped=Mock())
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)


def test_http_error_includes_server_explanation():
    session = Mock(request=Mock(side_effect=[_response([]), _response([_task(None)]),
                                            _response(status=400, text="locked by another worker")]))
    with pytest.raises(RuntimeError, match="HTTP 400: locked by another worker"):
        check_review_route(session, "http://engine", "parent", ensure_worker_stopped=Mock())


def test_already_at_review_is_read_only_and_idempotent():
    session = Mock(request=Mock(return_value=_response([{"taskDefinitionKey": REVIEW_TASK}])))
    stopped = Mock()
    assert check_review_route(session, "http://engine", "parent", ensure_worker_stopped=stopped)["already_at_review"]
    stopped.assert_not_called()
    assert session.request.call_count == 1


def test_local_container_must_be_stopped(monkeypatch):
    monkeypatch.setattr("regression.check_review_route.subprocess.run", Mock(side_effect=[
        SimpleNamespace(returncode=0), SimpleNamespace(returncode=0, stdout="running", stderr="")]))
    with pytest.raises(RuntimeError, match="podman stop"):
        require_stopped_worker()
