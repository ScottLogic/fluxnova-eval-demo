"""Tests for ``main.parse_args`` (CLI flags + EVAL_SERVICE_* env var overrides)."""

from __future__ import annotations

from eval_service_worker import main as main_module


class TestParseArgs:
    def test_defaults_when_no_flags_or_env_vars(self, monkeypatch):
        for name in (
            "EVAL_SERVICE_FLUXNOVA_URL",
            "EVAL_SERVICE_EXPERIMENT_NAME",
            "EVAL_SERVICE_PROCESS_KEY",
            "EVAL_SERVICE_TOPIC",
            "EVAL_SERVICE_JUDGE_MODEL",
            "EVAL_SERVICE_LOCK_DURATION_MS",
            "EVAL_SERVICE_TRACKING_URI",
            "EVAL_SERVICE_TRACE_POLL_TIMEOUT",
            "EVAL_SERVICE_TRACE_POLL_INTERVAL",
        ):
            monkeypatch.delenv(name, raising=False)

        args = main_module.parse_args([])

        assert args.fluxnova_url == "http://localhost:8080/engine-rest"
        assert args.tracking_uri == "http://localhost:5000"
        assert args.topic == "agent-output-eval"
        assert args.lock_duration_ms == 180_000
        assert args.trace_poll_timeout == 30.0
        assert args.trace_poll_interval == 3.0

    def test_cli_flags_override_defaults(self):
        args = main_module.parse_args(
            [
                "--fluxnova-url",
                "http://fluxnova-local:8080/engine-rest",
                "--tracking-uri",
                "http://mlflow-local:5000",
                "--topic",
                "custom-topic",
            ]
        )

        assert args.fluxnova_url == "http://fluxnova-local:8080/engine-rest"
        assert args.tracking_uri == "http://mlflow-local:5000"
        assert args.topic == "custom-topic"

    def test_env_vars_override_defaults_when_no_flag_given(self, monkeypatch):
        monkeypatch.setenv("EVAL_SERVICE_FLUXNOVA_URL", "http://from-env:8080/engine-rest")
        monkeypatch.setenv("EVAL_SERVICE_LOCK_DURATION_MS", "60000")

        args = main_module.parse_args([])

        assert args.fluxnova_url == "http://from-env:8080/engine-rest"
        assert args.lock_duration_ms == 60_000

    def test_cli_flag_takes_precedence_over_env_var(self, monkeypatch):
        monkeypatch.setenv("EVAL_SERVICE_TOPIC", "from-env-topic")

        args = main_module.parse_args(["--topic", "from-flag-topic"])

        assert args.topic == "from-flag-topic"
