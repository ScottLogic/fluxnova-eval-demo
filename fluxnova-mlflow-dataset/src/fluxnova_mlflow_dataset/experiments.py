"""Validate artifact routing before host or sibling-container clients log data."""

from __future__ import annotations

import re
from urllib.parse import urlparse


def require_remote_artifacts(experiment) -> None:
    location = experiment.artifact_location or ""
    if urlparse(location).scheme in ("", "file") or re.match(r"^[A-Za-z]:[\\/]", location):
        raise ValueError(
            f"Experiment {experiment.name!r} advertises a local artifact path {location!r}. "
            "Configure MLflow with --serve-artifacts --artifacts-destination /mlflow-artifacts "
            "--default-artifact-root mlflow-artifacts:/ and select a fresh experiment name. "
            "Use MLFLOW_EXPERIMENT_NAME for regression; existing experiments are not migrated "
            "by a server restart and their results should be preserved."
        )
