"""pytest configuration for deep_eval tests.

Registers --config and --report CLI options so the test suite can be driven
by any workflow config + agent-history report pair:

    deepeval test run src/deep_eval/main.py --config harness/config/loan-assesment.yml \\
        --report harness/.fluxnova/loanAssessmentProcess/<id>.json

    pytest src/deep_eval/main.py -v --config ... --report ...
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fluxnova.config import WorkflowConfig


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--config", default=None, help="Path to workflow YAML config file")
    parser.addoption("--report", default=None, help="Path to agent-history JSON report file")


@pytest.fixture(scope="session")
def workflow_config(request: pytest.FixtureRequest) -> WorkflowConfig:
    path = request.config.getoption("--config")
    if not path:
        pytest.fail("--config is required. Pass the path to your workflow YAML config file.")
    return WorkflowConfig.from_file(Path(path))


@pytest.fixture(scope="session")
def agent_report(request: pytest.FixtureRequest) -> dict:
    path = request.config.getoption("--report")
    if not path:
        pytest.fail("--report is required. Pass the path to an agent-history JSON report file.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)
