import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fluxnova_mlflow_dataset import scorers as scorers_module

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


class _FakeScorer:
    def __init__(self, name: str, doc: str) -> None:
        self.name = name
        self.description = None

        def _original(*args: object, **kwargs: object) -> None:
            pass

        _original.__doc__ = doc
        self._original_func = _original


def test_deterministic_scorer_docstring_reads_original_func_doc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeScorer("some_check", "  Checks that something holds.\n  Multi-line.  ")
    monkeypatch.setattr(scorers_module, "ALL_DETERMINISTIC_SCORERS", [fake])
    description = regression_runner._deterministic_scorer_docstring("some_check")
    assert description == "Checks that something holds. Multi-line."


def test_deterministic_scorer_docstring_unknown_scorer_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scorers_module, "ALL_DETERMINISTIC_SCORERS", [])
    assert regression_runner._deterministic_scorer_docstring("nonexistent") == ""


def test_list_tests_uses_scorer_docstring_for_parametrized_deterministic_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    suite = tmp_path / "test_dummy_suite.py"
    suite.write_text(
        "import pytest\n"
        "\n"
        '@pytest.mark.parametrize("scorer_name", ["some_check"])\n'
        "def test_agent_passes_deterministic_check(scorer_name):\n"
        '    """Shared generic docstring, should be overridden per scorer."""\n'
        "    assert True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(regression_runner, "REGRESSION_DIR", tmp_path)
    monkeypatch.setattr(regression_runner, "REGRESSION_TEST_FILE", suite)
    fake = _FakeScorer("some_check", "The real, scorer-specific description.")
    monkeypatch.setattr(scorers_module, "ALL_DETERMINISTIC_SCORERS", [fake])

    tests = regression_runner.list_tests()
    assert tests == [
        {
            "name": "test_dummy_suite.py::test_agent_passes_deterministic_check[some_check]",
            "description": "The real, scorer-specific description.",
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
