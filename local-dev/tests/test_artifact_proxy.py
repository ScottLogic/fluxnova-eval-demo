"""Real host/server artifact round-trip against an isolated temporary MLflow store."""

import importlib.util
import os
import runpy
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.skipif(os.environ.get("RUN_MLFLOW_PROXY_TEST") != "1", reason="opt-in isolated MLflow server test")
def test_host_artifact_round_trip(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_artifacts", Path(__file__).parents[1] / "mlflow/check_artifacts.py")
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    uri = f"http://127.0.0.1:{port}"
    command = [sys.executable, "-m", "mlflow", "server", "--backend-store-uri",
               f"sqlite:///{tmp_path / 'tracking.db'}", "--serve-artifacts",
               "--artifacts-destination", str(tmp_path / "artifacts"),
               "--default-artifact-root", "mlflow-artifacts:/", "--host", "127.0.0.1",
               "--port", str(port), "--workers", "1"]
    with (tmp_path / "server.log").open("w+") as log:
        server = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, cwd=tmp_path,
            start_new_session=os.name != "nt",
        )
        try:
            deadline = time.monotonic() + 60
            while True:
                try:
                    with urllib.request.urlopen(uri + "/version", timeout=1):
                        break
                except (urllib.error.URLError, TimeoutError):
                    if server.poll() is not None or time.monotonic() > deadline:
                        log.seek(0)
                        pytest.fail("MLflow did not start: " + log.read())
                    time.sleep(0.2)
            run_id = check.check_artifacts(uri, "proxy-smoke")
            run = check.MlflowClient(tracking_uri=uri).get_run(run_id)
            assert run.info.artifact_uri.startswith("mlflow-artifacts:/")
            assert run.info.status == "FINISHED"
            # Exercise the full evaluate result schema and HTTP report transport
            # with a code-only scorer, without a model or workflow.
            import json

            import mlflow
            from mlflow.genai.scorers import scorer

            inputs = {"input_variables": {}, "scenario": "proxy-smoke", "process_instance_id": "frozen-process"}
            @scorer
            def score(inputs, outputs) -> bool:
                return outputs == "APPROVE"

            def predict(input_variables, **_scorer_only_fields):
                return "APPROVE"
            module = runpy.run_path(str(Path(__file__).parents[2] / "regression/test_mlflow_regression.py"))
            monkeypatch.setenv("REGRESSION_REPORT_DIR", str(tmp_path / "reports"))
            previous_uri = mlflow.get_tracking_uri()
            mlflow.set_tracking_uri(uri)
            try:
                report_experiment = mlflow.set_experiment("report-smoke")
                with mlflow.start_run(experiment_id=report_experiment.experiment_id):
                    scored = mlflow.genai.evaluate(data=[{"inputs": inputs}], predict_fn=predict, scorers=[score])
                table = scored.tables["eval_results"]
                assert {"request", "response", "assessments"} <= set(table.columns)
                module["_report_gate"](SimpleNamespace(tables={"eval_results": table}, run_id=scored.run_id),
                                       [{"inputs": inputs}], ["score"], "smoke")
            finally:
                mlflow.set_tracking_uri(previous_uri)
            report_path = check.MlflowClient(tracking_uri=uri).download_artifacts(scored.run_id, "regression/smoke.json", str(tmp_path))
            assert json.loads(Path(report_path).read_text())["cases"][0]["scenario"] == "proxy-smoke"
            if os.environ.get("RUN_LLM_CALIBRATION_TEST") == "1":
                from dotenv import load_dotenv

                from regression.calibrate import DEFAULT_CASES, load_cases, run_judge
                from regression.reporting import failure_message, write_report

                load_dotenv(Path(__file__).parents[2] / "local-dev/.env")
                calibration = run_judge(load_cases(DEFAULT_CASES), uri, "isolated-calibration")
                saved = Path(__file__).parents[2] / f"local-dev/.mlflow/calibration/isolated-{calibration['run_id']}.json"
                write_report(calibration, saved)
                assert not calibration["failures"], failure_message(calibration)
        finally:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], check=False, capture_output=True)
            else:
                try:
                    os.killpg(server.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
