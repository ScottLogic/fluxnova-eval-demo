"""Real host/server artifact round-trip against an isolated temporary MLflow store."""

import importlib.util
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get("RUN_MLFLOW_PROXY_TEST") != "1", reason="opt-in isolated MLflow server test")
def test_host_artifact_round_trip(tmp_path):
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
