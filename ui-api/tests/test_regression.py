import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ui_api import regression_runner
from ui_api.app import create_app

_DUMMY_SUITE = '''
def test_pass():
    assert True


def test_fail():
    assert False
'''


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    test_file = tmp_path / "test_dummy_suite.py"
    test_file.write_text(_DUMMY_SUITE)
    monkeypatch.setattr(regression_runner, "REGRESSION_DIR", tmp_path)
    monkeypatch.setattr(regression_runner, "REGRESSION_TEST_FILE", test_file)
    return TestClient(create_app())


def test_list_tests(client: TestClient) -> None:
    response = client.get("/api/regression/tests")
    assert response.status_code == 200
    assert response.json() == {
        "tests": ["test_dummy_suite.py::test_pass", "test_dummy_suite.py::test_fail"]
    }


def test_unknown_run_returns_404(client: TestClient) -> None:
    response = client.get("/api/regression/runs/does-not-exist")
    assert response.status_code == 404


def test_start_and_poll_run(client: TestClient) -> None:
    response = client.post("/api/regression/runs")
    assert response.status_code == 202
    run_id = response.json()["runId"]

    for _ in range(100):
        result = client.get(f"/api/regression/runs/{run_id}").json()
        if result["status"] != "running":
            break
        time.sleep(0.1)
    else:
        pytest.fail("Run did not finish in time")

    assert result["status"] == "failed"
    assert result["exitCode"] == 1
    outcomes = {test["nodeId"]: test["outcome"] for test in result["tests"]}
    assert outcomes == {
        "test_dummy_suite.py::test_pass": "passed",
        "test_dummy_suite.py::test_fail": "failed",
    }
