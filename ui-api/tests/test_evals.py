import pytest
from fastapi.testclient import TestClient

from ui_api import listener_client
from ui_api.app import create_app


class _FakeListener:
    def __init__(self, initial: float = 1.0) -> None:
        self.sample_rate = initial

    def get(self) -> float:
        return self.sample_rate

    def set(self, rate: float) -> float:
        self.sample_rate = max(0.0, min(1.0, rate))
        return self.sample_rate


@pytest.fixture
def listener(monkeypatch: pytest.MonkeyPatch) -> _FakeListener:
    fake = _FakeListener()
    monkeypatch.setattr(listener_client, "get_sample_rate", fake.get)
    monkeypatch.setattr(listener_client, "set_sample_rate", fake.set)
    return fake


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_get_auto_eval_reports_enabled_when_sample_rate_positive(
    client: TestClient, listener: _FakeListener
) -> None:
    listener.sample_rate = 1.0
    response = client.get("/api/evals/auto-eval")
    assert response.status_code == 200
    assert response.json() == {"enabled": True}


def test_get_auto_eval_reports_disabled_when_sample_rate_zero(
    client: TestClient, listener: _FakeListener
) -> None:
    listener.sample_rate = 0.0
    response = client.get("/api/evals/auto-eval")
    assert response.status_code == 200
    assert response.json() == {"enabled": False}


def test_post_auto_eval_true_sets_full_sample_rate(
    client: TestClient, listener: _FakeListener
) -> None:
    response = client.post("/api/evals/auto-eval", json={"enabled": True})
    assert response.status_code == 200
    assert response.json() == {"enabled": True}
    assert listener.sample_rate == 1.0


def test_post_auto_eval_false_sets_zero_sample_rate(
    client: TestClient, listener: _FakeListener
) -> None:
    response = client.post("/api/evals/auto-eval", json={"enabled": False})
    assert response.status_code == 200
    assert response.json() == {"enabled": False}
    assert listener.sample_rate == 0.0


def test_get_auto_eval_returns_502_when_listener_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_error() -> float:
        raise listener_client.ListenerControlError("connection refused")

    monkeypatch.setattr(listener_client, "get_sample_rate", raise_error)
    response = client.get("/api/evals/auto-eval")
    assert response.status_code == 502


def test_get_definitions_returns_real_scorer_names(client: TestClient) -> None:
    response = client.get("/api/evals/definitions")
    assert response.status_code == 200
    body = response.json()

    listener_names = {scorer["name"] for scorer in body["listener"]}
    assert "decision_quality" in listener_names
    assert "evidence_citation" in listener_names
    assert "step_efficiency" in listener_names

    worker_names = {scorer["name"] for scorer in body["serviceWorker"]}
    assert "decision_quality" in worker_names
    assert "step_efficiency" in worker_names
    # evidence_citation is listener-only (needs a golden the worker doesn't have).
    assert "evidence_citation" not in worker_names

    for scorer in body["listener"] + body["serviceWorker"]:
        assert set(scorer) == {"name", "description"}
