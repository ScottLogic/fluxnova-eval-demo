from pathlib import Path

from fluxnova_runner.config import RunnerConfig


def test_host_engine_url_can_override_workflow_without_editing_yaml(monkeypatch, tmp_path):
    config = tmp_path / "workflow.yml"
    config.write_text(
        "fluxnova_url: http://localhost:8080/engine-rest\nbpmn_path: bpmn/loan-assesment.bpmn\nprocess_key: loanAssessmentProcess\n"
    )
    monkeypatch.setenv("FLUXNOVA_URL", "http://localhost:18080/engine-rest/")
    assert RunnerConfig.from_file(config).fluxnova_url == "http://localhost:18080/engine-rest"


def test_additional_resources_are_deployed_with_the_bpmn(tmp_path):
    config = tmp_path / "workflow.yml"
    config.write_text(
        "fluxnova_url: http://engine/engine-rest\n"
        "bpmn_path: bpmn/main.bpmn\n"
        "additional_bpmn_paths: [bpmn/sub.bpmn]\n"
        "additional_resources: [bpmn/forms/review.form]\n"
        "process_key: p\n"
        "deployment_name: d\n"
    )
    cfg = RunnerConfig.from_file(config)
    assert [p.name for p in cfg.deployment_paths] == ["sub.bpmn", "review.form"]
    assert cfg.deployment_paths[1].is_absolute()


def test_real_workflow_config_deploys_review_form():
    root = Path(__file__).resolve().parents[2]
    cfg = RunnerConfig.from_file(root / "fluxnova-runner/config/loan_approval_process_ai.yml")
    form = next(p for p in cfg.additional_resources if p.suffix == ".form")
    assert form.is_file()
    assert '"id": "risk_assessment_review"' in form.read_text(encoding="utf-8")
