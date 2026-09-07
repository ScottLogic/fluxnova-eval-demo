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
