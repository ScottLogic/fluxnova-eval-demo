from __future__ import annotations

import textwrap
from pathlib import Path

from eval_async_worker.config import AsyncWorkerConfig
from eval_async_worker.main import _build_config, parse_args


def test_defaults() -> None:
    config = AsyncWorkerConfig()
    assert config.fluxnova_url == "http://localhost:8080/engine-rest"
    assert config.topic == "agent-output-eval-async"
    assert config.lock_duration_ms == 600_000
    assert config.tracking_uri == "http://localhost:5001"
    assert config.experiment_name == "fluxnova-loanAssessmentEvalProcess"
    assert config.trace_poll_timeout_s == 90.0
    assert config.trace_poll_interval_s == 3.0
    assert config.sample_rate == 1.0
    assert config.control_host == "0.0.0.0"
    assert config.control_port == 8092


def test_from_mapping_overrides_and_ignores_unknown() -> None:
    config = AsyncWorkerConfig.from_mapping(
        {
            "fluxnova_url": "http://fluxnova-local:8080/engine-rest/",
            "topic": "other-topic",
            "tracking_uri": "http://mlflow-local:5000/",
            "sample_rate": 0.5,
            "control_port": 9999,
            "agent_names": ["legacy setting, ignored"],
        }
    )
    assert config.fluxnova_url == "http://fluxnova-local:8080/engine-rest"
    assert config.topic == "other-topic"
    assert config.tracking_uri == "http://mlflow-local:5000"
    assert config.sample_rate == 0.5
    assert config.control_port == 9999
    assert config.experiment_name == "fluxnova-loanAssessmentEvalProcess"


def test_from_mapping_none_gives_defaults() -> None:
    assert AsyncWorkerConfig.from_mapping(None) == AsyncWorkerConfig()


def test_from_file(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        textwrap.dedent(
            """
            topic: t
            trace_poll_timeout_s: 5
            """
        ),
        encoding="utf-8",
    )
    config = AsyncWorkerConfig.from_file(path)
    assert config.topic == "t"
    assert config.trace_poll_timeout_s == 5.0


def test_bundled_config_file_matches_defaults() -> None:
    bundled = Path(__file__).resolve().parents[1] / "config.yaml"
    assert AsyncWorkerConfig.from_file(bundled) == AsyncWorkerConfig()


def test_cli_beats_env_beats_file(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("topic: from-file\nsample_rate: 0.1\nexperiment_name: file-exp\n")
    monkeypatch.setenv("EVAL_ASYNC_TOPIC", "from-env")
    monkeypatch.setenv("EVAL_ASYNC_SAMPLE_RATE", "0.2")
    config = _build_config(parse_args(["--config", str(path), "--sample-rate", "0.3"]))
    assert config.topic == "from-env"
    assert config.sample_rate == 0.3
    assert config.experiment_name == "file-exp"
