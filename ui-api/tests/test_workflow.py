from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ui_api import workflow_runner
from ui_api.app import create_app

_CONFIG_YAML = """
fluxnova_url: http://fluxnova.invalid/engine-rest
bpmn_path: bpmn/does-not-matter.bpmn
process_key: someProcess
deployment_name: Some Deployment
variables:
  applicantName: Jane Smith
  requestedAmount: 50000
"""


class _FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def unlock_stale_external_tasks(self) -> list[str]:
        return []

    def delete_deployments_by_name(self, name: str) -> list[str]:
        return []

    def deploy(self, *args, **kwargs) -> dict:
        return {"id": "deployment-1", "name": "Some Deployment"}

    def start_process(self, process_key: str, variables: dict) -> str:
        self.started_with = variables
        return "instance-1"

    def get_instance(self, instance_id: str):
        return None

    def get_history(self, instance_id: str) -> dict:
        return {"state": "COMPLETED"}

    def get_variables(self, instance_id: str) -> dict:
        return {"recommendedDecision": "APPROVE"}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    config_path = tmp_path / "workflow.yml"
    config_path.write_text(_CONFIG_YAML)
    monkeypatch.setattr(workflow_runner, "CONFIG_PATH", config_path)
    monkeypatch.setattr(workflow_runner, "Client", _FakeClient)
    monkeypatch.setattr(workflow_runner, "start_workers", lambda *a, **k: [])
    monkeypatch.setattr(workflow_runner, "_mock_workers_started", False)
    return TestClient(create_app())


def test_start_run_returns_instance_id(client: TestClient) -> None:
    response = client.post("/api/workflow/runs", json={"requestedAmount": 75000})
    assert response.status_code == 202
    assert response.json() == {"instanceId": "instance-1"}


def test_get_run_reports_completed_status(client: TestClient) -> None:
    client.post("/api/workflow/runs")
    response = client.get("/api/workflow/runs/instance-1")
    assert response.status_code == 200
    assert response.json() == {
        "instanceId": "instance-1",
        "status": "completed",
        "state": "COMPLETED",
        "variables": {"recommendedDecision": "APPROVE"},
    }
