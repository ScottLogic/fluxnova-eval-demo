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
    # Serialize scoring: mlflow.genai.evaluate fans out every row's judge call
    # concurrently (MLFLOW_GENAI_EVAL_MAX_WORKERS defaults to 10). Against the
    # local CPU-bound Ollama judge (a single gemma4:e2b instance) those parallel
    # requests never get scheduled and every judge thread blocks forever in
    # socket.readinto with no client timeout, hanging the whole run. Capping to
    # one worker means one judge call hits Ollama at a time — the sequential path
    # that completes reliably. Overridable in CI where a scalable judge backend
    # can handle real concurrency.
    os.environ.setdefault("MLFLOW_GENAI_EVAL_MAX_WORKERS", "1")
