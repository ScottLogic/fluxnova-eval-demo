from __future__ import annotations

import textwrap
from pathlib import Path

from eval_trace_listener.config import ListenerConfig


def test_defaults() -> None:
    config = ListenerConfig()
    assert config.tracking_uri == "http://localhost:5001"
    assert config.experiment_name == "fluxnova-loanAssessmentEvalProcess"
    assert config.agent_names == ["AdHocSubProcess_LoanAssessmentAgent"]
    assert config.poll_interval_s == 10.0
    assert config.max_traces_per_poll == 200


def test_from_mapping_overrides_and_ignores_unknown() -> None:
    config = ListenerConfig.from_mapping(
        {
            "tracking_uri": "http://mlflow-local:5000/",
            "experiment_name": "fluxnova-somethingElse",
            "agent_names": ["A", "B"],
            "poll_interval_s": 3,
            "future_setting_we_dont_read_yet": True,
        }
    )
    assert config.tracking_uri == "http://mlflow-local:5000"  # trailing slash stripped
    assert config.experiment_name == "fluxnova-somethingElse"
    assert config.agent_names == ["A", "B"]
    assert config.poll_interval_s == 3.0
    # unspecified key falls back to default
    assert config.max_traces_per_poll == 200


def test_from_mapping_none_gives_defaults() -> None:
    assert ListenerConfig.from_mapping(None) == ListenerConfig()


def test_from_file(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        textwrap.dedent(
            """
            tracking_uri: http://host:5000
            experiment_name: fluxnova-x
            agent_names: []
            poll_interval_s: 1
            """
        ),
        encoding="utf-8",
    )
    config = ListenerConfig.from_file(path)
    assert config.experiment_name == "fluxnova-x"
    assert config.agent_names == []  # empty list => score every agent
    assert config.poll_interval_s == 1.0


def test_packaged_config_yaml_loads() -> None:
    """The config.yaml shipped in the package must stay parseable."""
    packaged = Path(__file__).resolve().parent.parent / "config.yaml"
    config = ListenerConfig.from_file(packaged)
    assert config.experiment_name == "fluxnova-loanAssessmentEvalProcess"
