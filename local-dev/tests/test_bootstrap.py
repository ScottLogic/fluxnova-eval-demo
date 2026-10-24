"""Startup contracts: fresh/existing stores and collector header publication."""

import importlib.util
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "bootstrap", Path(__file__).parents[1] / "mlflow/bootstrap.py"
)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def test_existing_experiment_is_reused(monkeypatch):
    request = Mock(
        return_value={
            "experiment": {"experiment_id": "42", "lifecycle_stage": "active", "artifact_location": "mlflow-artifacts:/42"}
        }
    )
    monkeypatch.setattr(bootstrap, "request", request)
    assert bootstrap.ensure_experiment("http://mlflow:5000", "demo with spaces") == "42"
    assert request.call_args.args[1].endswith("experiment_name=demo+with+spaces")
    assert request.call_count == 1


def test_fresh_store_creates_experiment(monkeypatch):
    missing = urllib.error.HTTPError("url", 404, "missing", {}, None)
    request = Mock(side_effect=[missing, {"experiment_id": "1"}])
    monkeypatch.setattr(bootstrap, "request", request)
    assert bootstrap.ensure_experiment("http://mlflow:5000", "demo") == "1"
    assert request.call_args.args == (
        "http://mlflow:5000",
        "/api/2.0/mlflow/experiments/create",
        {"name": "demo"},
    )


def test_deleted_experiment_is_not_silently_reused(monkeypatch):
    monkeypatch.setattr(
        bootstrap,
        "request",
        Mock(
            return_value={
                "experiment": {"experiment_id": "42", "lifecycle_stage": "deleted"}
            }
        ),
    )
    with pytest.raises(ValueError, match="restore"):
        bootstrap.ensure_experiment("http://mlflow:5000", "demo")


def test_retry_and_publish_string_header(monkeypatch, tmp_path):
    ensure = Mock(side_effect=[urllib.error.URLError("starting"), "27"])
    monkeypatch.setattr(bootstrap, "ensure_experiment", ensure)
    monkeypatch.setattr(bootstrap.time, "sleep", Mock())
    output = tmp_path / "runtime/headers.yaml"
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--output", str(output)])
    bootstrap.main()
    assert json.loads(output.read_text()) == {"x-mlflow-experiment-id": "27"}
    assert not output.with_suffix(".tmp").exists()


def test_invalid_request_fails_without_publishing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        bootstrap,
        "ensure_experiment",
        Mock(side_effect=urllib.error.HTTPError("url", 401, "unauthorized", {}, None)),
    )
    output = tmp_path / "headers.yaml"
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--output", str(output)])
    with pytest.raises(urllib.error.HTTPError):
        bootstrap.main()
    assert not output.exists()


def test_old_container_local_experiment_requires_fresh_name(monkeypatch):
    monkeypatch.setattr(bootstrap, "request", Mock(return_value={"experiment": {
        "experiment_id": "2", "artifact_location": "/mlflow-artifacts/2", "lifecycle_stage": "active"
    }}))
    with pytest.raises(ValueError, match="fresh name"):
        bootstrap.ensure_experiment("http://mlflow:5000", "old-demo")
