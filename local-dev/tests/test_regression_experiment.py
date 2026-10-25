import runpy
from pathlib import Path


def test_regression_honors_the_same_experiment_override_as_pytest_plugin(monkeypatch):
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "regression-proxied-v2")
    monkeypatch.setenv("EVAL_SERVICE_EXPERIMENT_NAME", "traces-proxied-v2")
    module = runpy.run_path(str(Path(__file__).parents[2] / "regression/test_mlflow_regression.py"))
    assert module["_REGRESSION_EXPERIMENT"] == "regression-proxied-v2"
    assert module["_TRACE_EXPERIMENT_NAME"] == "traces-proxied-v2"


def test_default_regression_experiment_matches_collector_and_plugin(monkeypatch):
    import os

    import dotenv

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("MLFLOW_EXPERIMENT_NAME", raising=False)
    monkeypatch.setenv("EVAL_SERVICE_EXPERIMENT_NAME", "shared-traces-v2")
    root = Path(__file__).parents[2] / "regression"
    conftest = runpy.run_path(str(root / "conftest.py"))
    conftest["pytest_configure"](None)
    module = runpy.run_path(str(root / "test_mlflow_regression.py"))
    assert module["_REGRESSION_EXPERIMENT"] == module["_TRACE_EXPERIMENT_NAME"] == "shared-traces-v2"
