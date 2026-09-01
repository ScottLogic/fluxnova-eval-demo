"""Tests for RunnerConfig, Client, and mock_workers helpers."""

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fluxnova_runner.client import ApiError, Client, _to_camunda_vars
from fluxnova_runner.config import RunnerConfig
from fluxnova_runner.mock_workers import _make_handler
from fluxnova_runner.mock_workers import _to_camunda_vars as mw_to_camunda_vars

# ---------------------------------------------------------------------------
# RunnerConfig
# ---------------------------------------------------------------------------


class TestRunnerConfig:
    def _cfg_file(self, tmp_path: Path, extra: str = "") -> Path:
        bpmn = tmp_path / "my.bpmn"
        bpmn.touch()
        cfg = tmp_path / "workflow.yml"
        cfg.write_text(
            textwrap.dedent(f"""\
                fluxnova_url: http://localhost:8080/engine-rest
                bpmn_path: {bpmn}
                process_key: myProcess
                deployment_name: My Deployment
            """) + extra
        )
        return cfg

    def test_loads_basic_fields(self, tmp_path: Path):
        cfg = RunnerConfig.from_file(self._cfg_file(tmp_path))
        assert cfg.fluxnova_url == "http://localhost:8080/engine-rest"
        assert cfg.process_key == "myProcess"
        assert cfg.variables == {}
        assert cfg.mock_workers == {}

    def test_loads_variables(self, tmp_path: Path):
        extra = "variables:\n  amount: 1000\n  name: Alice\n"
        cfg = RunnerConfig.from_file(self._cfg_file(tmp_path, extra))
        assert cfg.variables == {"amount": 1000, "name": "Alice"}

    def test_loads_mock_workers(self, tmp_path: Path):
        extra = textwrap.dedent("""\
            mock_workers:
              my-topic:
                score: 99
                passed: true
        """)
        cfg = RunnerConfig.from_file(self._cfg_file(tmp_path, extra))
        assert cfg.mock_workers == {"my-topic": {"score": 99, "passed": True}}

    def test_empty_mock_workers_defaults_to_empty_dict(self, tmp_path: Path):
        cfg = RunnerConfig.from_file(self._cfg_file(tmp_path))
        assert cfg.mock_workers == {}

    def test_absolute_bpmn_path_preserved(self, tmp_path: Path):
        bpmn = tmp_path / "my.bpmn"
        bpmn.touch()
        cfg = RunnerConfig.from_file(self._cfg_file(tmp_path))
        assert cfg.bpmn_path == bpmn

    def test_trailing_slash_stripped_from_url(self, tmp_path: Path):
        bpmn = tmp_path / "my.bpmn"
        bpmn.touch()
        cfg_file = tmp_path / "workflow.yml"
        cfg_file.write_text(
            f"fluxnova_url: http://localhost:8080/engine-rest/\n"
            f"bpmn_path: {bpmn}\n"
            f"process_key: p\n"
        )
        cfg = RunnerConfig.from_file(cfg_file)
        assert not cfg.fluxnova_url.endswith("/")

    def test_ignores_eval_only_extra_fields(self, tmp_path: Path):
        """Fields owned by the listener/eval tools (subprocess_id, available_tools,
        expected_tools, dataset_path, mlflow_dataset) should be silently ignored so
        the same YAML config can be reused by the runner without modification."""
        extra = textwrap.dedent("""\
            subprocess_id: AdHocSubProcess_LoanAssessmentAgent
            available_tools:
              ServiceTask_Foo: Foo
            expected_tools:
              - tool: Foo
            dataset_path: datasets/foo/goldens.json
            mlflow_dataset:
              enabled: true
        """)
        cfg = RunnerConfig.from_file(self._cfg_file(tmp_path, extra))
        assert cfg.process_key == "myProcess"


# ---------------------------------------------------------------------------
# _to_camunda_vars  (shared logic — tested via client's copy)
# ---------------------------------------------------------------------------


class TestToCamundaVars:
    def test_string_type(self):
        assert _to_camunda_vars({"name": "Alice"}) == {"name": {"value": "Alice", "type": "String"}}

    def test_integer_type(self):
        assert _to_camunda_vars({"score": 750}) == {"score": {"value": 750, "type": "Integer"}}

    def test_float_type(self):
        assert _to_camunda_vars({"ratio": 0.35}) == {"ratio": {"value": 0.35, "type": "Double"}}

    def test_bool_type(self):
        assert _to_camunda_vars({"ok": True}) == {"ok": {"value": True, "type": "Boolean"}}

    def test_unknown_type_falls_back_to_string(self):
        assert _to_camunda_vars({"obj": object()})["obj"]["type"] == "String"

    def test_empty_dict(self):
        assert _to_camunda_vars({}) == {}

    def test_mock_workers_copy_is_equivalent(self):
        data = {"score": 99, "name": "Alice", "ratio": 0.5, "ok": False}
        assert mw_to_camunda_vars(data) == _to_camunda_vars(data)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class TestClientInit:
    def test_basic_auth_set_when_credentials_provided(self):
        client = Client(base_url="http://localhost:8080", username="admin", password="secret")
        assert client._session.auth == ("admin", "secret")

    def test_no_auth_when_credentials_omitted(self):
        client = Client(base_url="http://localhost:8080")
        assert client._session.auth is None

    def test_root_defaults_to_cwd(self):
        client = Client(base_url="http://localhost:8080")
        assert client._root == Path.cwd()

    def test_root_stored_when_provided(self, tmp_path: Path):
        client = Client(base_url="http://localhost:8080", root=tmp_path)
        assert client._root == tmp_path


class TestClientStartProcess:
    def _client(self) -> Client:
        return Client(base_url="http://localhost:8080/engine-rest")

    def test_returns_instance_id(self):
        client = self._client()
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"id": "abc-123"}
        with patch.object(client._session, "post", return_value=mock_resp):
            assert client.start_process("myProcess", {"amount": 1000}) == "abc-123"

    def test_raises_on_http_error(self):
        client = self._client()
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 500
        mock_resp.text = "Internal error"
        with (
            patch.object(client._session, "post", return_value=mock_resp),
            pytest.raises(ApiError),
        ):
            client.start_process("myProcess")


class TestClientDeploy:
    def test_resolves_bpmn_path_from_root(self, tmp_path: Path):
        bpmn = tmp_path / "flows" / "my.bpmn"
        bpmn.parent.mkdir()
        bpmn.write_bytes(b"<bpmn/>")
        client = Client(base_url="http://localhost:8080", root=tmp_path)
        mock_resp = MagicMock(ok=True)
        mock_resp.json.return_value = {"name": "My Flow", "id": "1"}
        with patch.object(client._session, "post", return_value=mock_resp) as mock_post:
            client.deploy(Path("flows/my.bpmn"), "My Flow")
        _, kwargs = mock_post.call_args
        uploaded_path = list(kwargs["files"]["upload"])[0]
        assert uploaded_path == "my.bpmn"

    def test_raises_on_http_error(self, tmp_path: Path):
        bpmn = tmp_path / "my.bpmn"
        bpmn.write_bytes(b"<bpmn/>")
        client = Client(base_url="http://localhost:8080", root=tmp_path)
        mock_resp = MagicMock(ok=False, status_code=401, text="Unauthorized")
        with (
            patch.object(client._session, "post", return_value=mock_resp),
            pytest.raises(ApiError),
        ):
            client.deploy(Path("my.bpmn"), "My Flow")


class TestClientWaitForCompletion:
    def _client(self) -> Client:
        return Client(base_url="http://localhost:8080/engine-rest")

    def test_returns_variables_when_instance_completed(self):
        client = self._client()
        mock_404 = MagicMock(status_code=404)
        mock_history = MagicMock(ok=True)
        mock_history.json.return_value = {"state": "COMPLETED"}
        mock_vars = MagicMock(ok=True)
        mock_vars.json.return_value = [{"name": "decision", "value": "APPROVE"}]
        with patch.object(client._session, "get", side_effect=[mock_404, mock_history, mock_vars]):
            result = client.wait_for_completion("abc-123", poll_interval=0, timeout=5)
        assert result == {"decision": "APPROVE"}

    def test_raises_timeout_if_never_completes(self):
        client = self._client()
        mock_active = MagicMock(ok=True, status_code=200)
        mock_active.json.return_value = {"id": "abc-123"}
        with (
            patch.object(client._session, "get", return_value=mock_active),
            pytest.raises(TimeoutError),
        ):
            client.wait_for_completion("abc-123", poll_interval=0, timeout=0.01)


class TestClientWaitForActivityCompletion:
    def _client(self) -> Client:
        return Client(base_url="http://localhost:8080/engine-rest")

    def test_returns_activity_instance_once_finished(self):
        client = self._client()
        mock_empty = MagicMock(ok=True)
        mock_empty.json.return_value = []
        mock_finished = MagicMock(ok=True)
        mock_finished.json.return_value = [
            {"id": "act-1", "activityId": "AdHocSubProcess_LoanAssessmentAgent", "endTime": "..."}
        ]
        with patch.object(client._session, "get", side_effect=[mock_empty, mock_finished]) as mock_get:
            result = client.wait_for_activity_completion(
                "abc-123", "AdHocSubProcess_LoanAssessmentAgent", poll_interval=0, timeout=5
            )
        assert result["activityId"] == "AdHocSubProcess_LoanAssessmentAgent"
        _, kwargs = mock_get.call_args
        assert kwargs["params"] == {
            "processInstanceId": "abc-123",
            "activityId": "AdHocSubProcess_LoanAssessmentAgent",
            "finished": "true",
        }

    def test_raises_timeout_if_activity_never_finishes(self):
        client = self._client()
        mock_empty = MagicMock(ok=True)
        mock_empty.json.return_value = []
        with (
            patch.object(client._session, "get", return_value=mock_empty),
            pytest.raises(TimeoutError),
        ):
            client.wait_for_activity_completion(
                "abc-123", "AdHocSubProcess_LoanAssessmentAgent", poll_interval=0, timeout=0.01
            )


# ---------------------------------------------------------------------------
# mock_workers._make_handler
# ---------------------------------------------------------------------------


class TestMakeHandler:
    def test_complete_called_with_camunda_vars(self):
        handler = _make_handler("my-topic", {"score": 99, "passed": True})
        mock_task = MagicMock()
        mock_task.get_task_id.return_value = "task-1"
        handler(mock_task)
        mock_task.complete.assert_called_once_with(
            global_variables={
                "score": {"value": 99, "type": "Integer"},
                "passed": {"value": True, "type": "Boolean"},
            }
        )

    def test_empty_outputs(self):
        handler = _make_handler("no-output-topic", {})
        mock_task = MagicMock()
        mock_task.get_task_id.return_value = "task-2"
        handler(mock_task)
        mock_task.complete.assert_called_once_with(global_variables={})
