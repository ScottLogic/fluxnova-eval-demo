from fluxnova_runner.config import RunnerConfig


def test_host_engine_url_can_override_workflow_without_editing_yaml(monkeypatch, tmp_path):
    config = tmp_path / "workflow.yml"
    config.write_text(
        "fluxnova_url: http://localhost:8080/engine-rest\nbpmn_path: bpmn/loan-assesment.bpmn\nprocess_key: loanAssessmentProcess\n"
    )
    monkeypatch.setenv("FLUXNOVA_URL", "http://localhost:18080/engine-rest/")
    assert RunnerConfig.from_file(config).fluxnova_url == "http://localhost:18080/engine-rest"
