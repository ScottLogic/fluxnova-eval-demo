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
        return self.active_instance

    def get_history(self, instance_id: str) -> dict:
        return {"state": "COMPLETED"}

    def get_variables(self, instance_id: str) -> dict:
        return {"recommendedDecision": "APPROVE"}


_FakeClient.active_instance = None


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    config_path = tmp_path / "workflow.yml"
    config_path.write_text(_CONFIG_YAML)
    monkeypatch.setattr(workflow_runner, "CONFIG_PATH", config_path)
    monkeypatch.setattr(workflow_runner, "Client", _FakeClient)
    monkeypatch.setattr(workflow_runner, "start_workers", lambda *a, **k: [])
    monkeypatch.setattr(workflow_runner, "_mock_workers_started", False)
    monkeypatch.setattr(_FakeClient, "active_instance", None)
    return TestClient(create_app())


def test_get_config_returns_defaults(client: TestClient) -> None:
    response = client.get("/api/workflow/config")
    assert response.status_code == 200
    assert response.json() == {
        "processKey": "someProcess",
        "variables": {"applicantName": "Jane Smith", "requestedAmount": 50000},
        "agentConfig": None,
    }


def test_get_config_returns_agent_config_when_subprocess_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bpmn_path = tmp_path / "agent.bpmn"
    bpmn_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             xmlns:agent="http://fluxnova.finos.org/schema/1.0/ai/agent"
             id="Definitions_1">
  <process id="someProcess">
    <adHocSubProcess id="Agent_1">
      <extensionElements>
        <agent:config provider="openai" model="gpt-4o" systemPrompt="Be a good agent." />
      </extensionElements>
    </adHocSubProcess>
  </process>
</definitions>
"""
    )
    config_path = tmp_path / "workflow.yml"
    config_path.write_text(
        f"""
fluxnova_url: http://fluxnova.invalid/engine-rest
bpmn_path: {bpmn_path.as_posix()}
process_key: someProcess
subprocess_id: Agent_1
deployment_name: Some Deployment
variables:
  applicantName: Jane Smith
"""
    )
    monkeypatch.setattr(workflow_runner, "CONFIG_PATH", config_path)
    monkeypatch.setattr(workflow_runner, "Client", _FakeClient)
    monkeypatch.setattr(workflow_runner, "start_workers", lambda *a, **k: [])
    monkeypatch.setattr(workflow_runner, "_mock_workers_started", False)
    monkeypatch.setattr(_FakeClient, "active_instance", None)
    test_client = TestClient(create_app())

    response = test_client.get("/api/workflow/config")
    assert response.status_code == 200
    assert response.json()["agentConfig"] == {
        "provider": "openai",
        "model": "gpt-4o",
        "systemPrompt": "Be a good agent.",
    }


def test_start_run_returns_instance_id(client: TestClient) -> None:
    response = client.post("/api/workflow/runs", json={"requestedAmount": 75000})
    assert response.status_code == 202
    assert response.json() == {"instanceId": "instance-1"}


def test_start_run_passes_through_skip_eval_service_worker_override(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        _FakeClient,
        "start_process",
        lambda self, process_key, variables: captured.update(variables) or "instance-1",
    )
    response = client.post("/api/workflow/runs", json={"skipEvalServiceWorker": True})
    assert response.status_code == 202
    assert captured["skipEvalServiceWorker"] is True


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


def test_get_run_reports_active_status_with_variables(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_FakeClient, "active_instance", {"id": "instance-1"})
    client.post("/api/workflow/runs")
    response = client.get("/api/workflow/runs/instance-1")
    assert response.status_code == 200
    assert response.json() == {
        "instanceId": "instance-1",
        "status": "active",
        "variables": {"recommendedDecision": "APPROVE"},
    }
