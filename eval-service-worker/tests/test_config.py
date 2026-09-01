"""Tests for ``EvalServiceConfig`` (hardcoded defaults, no config file)."""

from __future__ import annotations

from eval_service_worker.config import EvalServiceConfig


class TestEvalServiceConfig:
    def test_defaults_match_documented_values(self):
        config = EvalServiceConfig()

        assert config.fluxnova_url == "http://localhost:8080/engine-rest"
        assert config.experiment_name == "fluxnova-loanAssessmentEvalProcess"
        assert config.process_key == "loanAssessmentEvalProcess"
        assert config.topic == "agent-output-eval"
        assert config.judge_model == "gateway:/fluxnova-judge"
        assert config.lock_duration_ms == 180_000
        assert config.tracking_uri == "http://localhost:5000"
        assert config.trace_poll_timeout == 30.0
        assert config.trace_poll_interval == 3.0

    def test_fields_can_be_overridden(self):
        config = EvalServiceConfig(
            fluxnova_url="http://fluxnova-local:8080/engine-rest",
            experiment_name="fluxnova-loanAssessmentProcess-demo",
            tracking_uri="http://mlflow-local:5000",
            topic="custom-eval-topic",
        )

        assert config.fluxnova_url == "http://fluxnova-local:8080/engine-rest"
        assert config.experiment_name == "fluxnova-loanAssessmentProcess-demo"
        assert config.tracking_uri == "http://mlflow-local:5000"
        assert config.topic == "custom-eval-topic"
        # Untouched fields keep their defaults.
        assert config.judge_model == "gateway:/fluxnova-judge"
