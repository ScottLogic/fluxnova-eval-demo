import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ui_api import regression_runner
from ui_api.app import create_app

_DUMMY_SUITE = '''
def test_pass(json_metadata):
    json_metadata["scorers"] = [{"name": "some_check", "status": "passed", "value": True, "rationale": "OK"}]


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
        "tests": [
            {"name": "test_dummy_suite.py::test_pass", "description": ""},
            {"name": "test_dummy_suite.py::test_fail", "description": ""},
        ]
    }


def test_unknown_run_returns_404(client: TestClient) -> None:
    response = client.get("/api/regression/runs/does-not-exist")
    assert response.status_code == 404


def test_parse_partial_results_handles_inline_and_split_console_formats() -> None:
    # "test_a" finishes with nothing else printed (the plain single-line form);
    # "test_b" has log_cli output interleaved (nodeid alone, then log lines, then
    # a bare outcome line — see regression/pytest.ini's log_cli setting); "test_c"
    # has started (nodeid line seen) but has no outcome line yet, so it's "running".
    output = (
        "test_mlflow_regression.py::test_a PASSED                          [ 25%]\n"
        "test_mlflow_regression.py::test_b \n"
        "-------------------------------- live log setup --------------------------------\n"
        "10:20:15 INFO doing something\n"
        "FAILED                                                            [ 50%]\n"
        "test_mlflow_regression.py::test_c \n"
        "-------------------------------- live log call ---------------------------------\n"
        "10:20:20 INFO still going\n"
    )
    results = regression_runner._parse_partial_results(output, "test_mlflow_regression.py::")
    assert results == [
        {"nodeId": "test_mlflow_regression.py::test_a", "outcome": "passed", "durationSeconds": None},
        {"nodeId": "test_mlflow_regression.py::test_b", "outcome": "failed", "durationSeconds": None},
        {"nodeId": "test_mlflow_regression.py::test_c", "outcome": "running", "durationSeconds": None},
    ]


def test_parse_partial_results_ignores_unrelated_lines() -> None:
    output = (
        "============================= test session starts =============================\n"
        "collecting ... collected 2 items\n"
        "test_mlflow_regression.py::test_a PASSED                          [ 50%]\n"
        "====================== 1 passed in 0.12s ======================\n"
    )
    results = regression_runner._parse_partial_results(output, "test_mlflow_regression.py::")
    assert results == [
        {"nodeId": "test_mlflow_regression.py::test_a", "outcome": "passed", "durationSeconds": None},
    ]


def _write_goldens(path: Path, *goldens: dict) -> None:
    path.write_text(json.dumps(list(goldens)), encoding="utf-8")


def test_golden_description_reads_matching_golden_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    goldens_path = tmp_path / "goldens.json"
    _write_goldens(
        goldens_path,
        {"input": "First prompt.", "additional_metadata": {"scenario": "first"}},
        {"input": "Second prompt.", "additional_metadata": {"scenario": "second"}},
    )
    monkeypatch.setattr(regression_runner, "GOLDENS_PATH", goldens_path)
    assert regression_runner._golden_description("second") == "Second prompt."
    assert regression_runner._golden_description("nonexistent") == ""


def test_golden_description_missing_goldens_file_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(regression_runner, "GOLDENS_PATH", tmp_path / "missing.json")
    assert regression_runner._golden_description("anything") == ""


def test_list_tests_uses_golden_input_for_parametrized_golden_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suite = tmp_path / "test_dummy_suite.py"
    suite.write_text(
        "import pytest\n"
        "\n"
        '@pytest.mark.parametrize("scenario", ["some-scenario"])\n'
        "def test_agent_passes_golden(scenario):\n"
        '    """Shared generic docstring, should be overridden per golden."""\n'
        "    assert True\n",
        encoding="utf-8",
    )
    goldens_path = tmp_path / "goldens.json"
    _write_goldens(
        goldens_path,
        {"input": "The scenario-specific prompt.", "additional_metadata": {"scenario": "some-scenario"}},
    )
    monkeypatch.setattr(regression_runner, "REGRESSION_DIR", tmp_path)
    monkeypatch.setattr(regression_runner, "REGRESSION_TEST_FILE", suite)
    monkeypatch.setattr(regression_runner, "GOLDENS_PATH", goldens_path)

    tests = regression_runner.list_tests()
    assert tests == [
        {
            "name": "test_dummy_suite.py::test_agent_passes_golden[some-scenario]",
            "description": "The scenario-specific prompt.",
        }
    ]


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
    scorers = {test["nodeId"]: test["scorers"] for test in result["tests"]}
    assert scorers == {
        "test_dummy_suite.py::test_pass": [
            {"name": "some_check", "status": "passed", "value": True, "rationale": "OK"}
        ],
        "test_dummy_suite.py::test_fail": None,
    }
