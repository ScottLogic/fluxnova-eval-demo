"""Tests for the read-only Fluxnova REST client, focused on child-instance lookup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fluxnova_mlflow_dataset import ApiError, FluxnovaClient


def _client() -> FluxnovaClient:
    return FluxnovaClient(base_url="http://localhost:8080/engine-rest")


class TestGetChildInstanceId:
    def test_returns_child_id_when_present(self):
        client = _client()
        resp = MagicMock(ok=True)
        resp.json.return_value = [{"id": "child-1", "startTime": "2026-09-04T10:00:00"}]
        with patch.object(client._session, "get", return_value=resp) as mock_get:
            assert client.get_child_instance_id("parent-1") == "child-1"
        _, kwargs = mock_get.call_args
        assert kwargs["params"] == {"superProcessInstanceId": "parent-1"}

    def test_returns_none_when_no_child(self):
        client = _client()
        resp = MagicMock(ok=True)
        resp.json.return_value = []
        with patch.object(client._session, "get", return_value=resp):
            assert client.get_child_instance_id("parent-1") is None

    def test_returns_most_recent_child_when_multiple(self):
        client = _client()
        resp = MagicMock(ok=True)
        resp.json.return_value = [
            {"id": "older", "startTime": "2026-09-04T09:00:00"},
            {"id": "newer", "startTime": "2026-09-04T10:00:00"},
        ]
        with patch.object(client._session, "get", return_value=resp):
            assert client.get_child_instance_id("parent-1") == "newer"

    def test_raises_on_http_error(self):
        client = _client()
        resp = MagicMock(ok=False, status_code=500, text="boom")
        with (
            patch.object(client._session, "get", return_value=resp),
            pytest.raises(ApiError),
        ):
            client.get_child_instance_id("parent-1")


if __name__ == "__main__":
    pytest.main([__file__])


class TestGetProcessDefinitionXml:
    def test_reads_deployed_definition_of_instance(self):
        client = _client()
        instance = MagicMock(ok=True)
        instance.json.return_value = {"processDefinitionId": "def:1"}
        xml = MagicMock(ok=True)
        xml.json.return_value = {"bpmn20Xml": "<definitions/>"}
        with patch.object(client._session, "get", side_effect=[instance, xml]) as mock_get:
            assert client.get_process_definition_xml("child-1") == "<definitions/>"
        urls = [call.args[0] for call in mock_get.call_args_list]
        assert urls == [
            "http://localhost:8080/engine-rest/history/process-instance/child-1",
            "http://localhost:8080/engine-rest/process-definition/def:1/xml",
        ]

    def test_raises_on_http_error(self):
        client = _client()
        error = MagicMock(ok=False, status_code=404)
        with patch.object(client._session, "get", return_value=error), pytest.raises(ApiError):
            client.get_process_definition_xml("missing")


class TestGetRunNumber:
    def test_counts_runs_of_same_definition_started_up_to_this_one(self):
        client = _client()
        instance = MagicMock(ok=True)
        instance.json.return_value = {
            "processDefinitionKey": "LoanApprovalProcess_AI",
            "startTime": "2026-11-09T11:40:51.119Z",
        }
        count = MagicMock(ok=True)
        count.json.return_value = {"count": 33}
        with patch.object(client._session, "get", side_effect=[instance, count]) as mock_get:
            assert client.get_run_number("pi-33") == 33
        assert mock_get.call_args_list[1].kwargs["params"] == {
            "processDefinitionKey": "LoanApprovalProcess_AI",
            "startedBefore": "2026-11-09T11:40:51.119+0000",
        }

    @pytest.mark.parametrize(
        "engine_value",
        ["2026-11-10T10:40:54.956+00:00", "2026-11-10T10:40:54.956Z", "2026-11-10T10:40:54.956+0000"],
    )
    def test_normalises_engine_date_formats_for_the_query(self, engine_value):
        from fluxnova_mlflow_dataset.fluxnova_client import _engine_date

        assert _engine_date(engine_value) == "2026-11-10T10:40:54.956+0000"

    def test_keeps_non_utc_offsets(self):
        from fluxnova_mlflow_dataset.fluxnova_client import _engine_date

        assert _engine_date("2026-11-10T11:40:54.956+01:00") == "2026-11-10T11:40:54.956+0100"
