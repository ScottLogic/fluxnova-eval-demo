import pytest
from fastapi.testclient import TestClient

from ui_api.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_get_definitions_returns_complete_scorer_matrix(client: TestClient) -> None:
    response = client.get("/api/evals/definitions")
    assert response.status_code == 200
    scorers = {scorer["name"]: scorer for scorer in response.json()["scorers"]}

    for scorer in scorers.values():
        assert set(scorer) == {
            "name",
            "description",
            "deterministic",
            "usedInAutoEval",
            "usedInEvalServiceWorker",
            "usedInRegression",
        }
        # regression/test_mlflow_regression.py exercises every scorer that exists.
        assert scorer["usedInRegression"] is True

    # LLM judges: non-deterministic, and each used in a different subset of places.
    assert scorers["decision_quality"]["deterministic"] is False
    assert scorers["decision_quality"]["usedInAutoEval"] is True
    assert scorers["decision_quality"]["usedInEvalServiceWorker"] is True

    assert scorers["evidence_citation"]["deterministic"] is False
    assert scorers["evidence_citation"]["usedInAutoEval"] is True
    # evidence_citation needs data (agent_goal) the worker's trace-only inputs don't
    # carry, so it never runs there — see eval_definitions.all_scorers's docstring.
    assert scorers["evidence_citation"]["usedInEvalServiceWorker"] is False

    assert scorers["matches_golden"]["deterministic"] is False
    assert scorers["matches_golden"]["usedInAutoEval"] is False
    assert scorers["matches_golden"]["usedInEvalServiceWorker"] is False

    # A deterministic check used everywhere.
    assert scorers["step_efficiency"]["deterministic"] is True
    assert scorers["step_efficiency"]["usedInAutoEval"] is True
    assert scorers["step_efficiency"]["usedInEvalServiceWorker"] is True

    # Tool-argument scorers are deterministic but regression-only.
    assert scorers["tool_argument_correctness"]["deterministic"] is True
    assert scorers["tool_argument_correctness"]["usedInAutoEval"] is False
    assert scorers["tool_argument_correctness"]["usedInEvalServiceWorker"] is False
