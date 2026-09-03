"""pytest configuration for the harness regression suite.

The ``@mlflow.test`` plugin (enabled via ``-p mlflow.pytest.plugin`` in
``addopts``) opens the test's MLflow run *before* the test body runs, using
whatever tracking store and experiment are configured at that moment. If those
were only selected inside the test body, the run would already be open in the
ambient local ``./mlruns`` store and get orphaned once the body switched to the
shared Postgres store — breaking ``evaluate()``'s dataset logging with
``Run not found``.

Selecting the store + experiment here, in ``pytest_configure`` (which runs
before any test call), ensures the plugin opens the run directly in the shared
Postgres backend store under the dedicated regression experiment. ``setdefault``
leaves any externally-provided override (e.g. a CI-provided
``MLFLOW_TRACKING_URI``) intact, and only sets env — it does not touch the store
— so an unreachable store still skips cleanly inside the test rather than
erroring during collection.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fluxnova_mlflow_dataset import default_tracking_uri, experiment_name_for

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def pytest_configure(config: pytest.Config) -> None:
    os.environ.setdefault("MLFLOW_TRACKING_URI", default_tracking_uri(_REPO_ROOT))
    os.environ.setdefault(
        "MLFLOW_EXPERIMENT_NAME",
        experiment_name_for("loanAssessmentProcess-regression"),
    )
