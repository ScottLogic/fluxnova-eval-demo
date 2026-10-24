import runpy
from pathlib import Path


def test_regression_honors_the_same_experiment_override_as_pytest_plugin(monkeypatch):
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "regression-proxied-v2")
    module = runpy.run_path(str(Path(__file__).parents[2] / "regression/test_mlflow_regression.py"))
    assert module["_REGRESSION_EXPERIMENT"] == "regression-proxied-v2"
