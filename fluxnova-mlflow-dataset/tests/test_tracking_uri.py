"""The host port default and explicit overrides must agree across CLI consumers."""

from unittest.mock import Mock

import pytest

from fluxnova_mlflow_dataset import judges
from fluxnova_mlflow_dataset.store import default_server_tracking_uri


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        (None, None, "http://localhost:5001"),
        ("mlflow.example", "15001", "http://mlflow.example:15001"),
    ],
)
def test_host_defaults_and_judges_cli_use_same_uri(monkeypatch, host, port, expected):
    for name, value in [("MLFLOW_HOST", host), ("MLFLOW_PORT", port)]:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert default_server_tracking_uri() == expected
    status = Mock()
    monkeypatch.setattr(judges, "_cmd_status", status)
    judges.main(["--experiment", "demo", "status"])
    assert status.call_args.args[0].tracking_uri == expected
