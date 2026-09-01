"""Thin adapter over the shared ``fluxnova_mlflow_dataset`` package.

The actual record-shaping/read/write/collect logic lives in the standalone
``fluxnova-mlflow-dataset`` package. This module just adapts it to accept a
harness ``WorkflowConfig`` object, so the existing ``mlflow_eval.main`` call
sites don't need to change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fluxnova_mlflow_dataset import (
    build_mlflow_record as _build_mlflow_record,
)
from fluxnova_mlflow_dataset import (
    dataset_name_for as _dataset_name_for,
)
from fluxnova_mlflow_dataset import (
    experiment_name_for as _experiment_name_for,
)
from fluxnova_mlflow_dataset import (
    get_or_create_dataset,
    resolve_expected_tools,
)
from fluxnova_mlflow_dataset import (
    tracking_uri_for as _tracking_uri_for,
)
from fluxnova_mlflow_dataset import (
    write_to_mlflow_dataset as _write_to_mlflow_dataset,
)

from fluxnova.config import WorkflowConfig

__all__ = [
    "experiment_name_for",
    "dataset_name_for",
    "tracking_uri_for",
    "resolve_expected_tools",
    "get_or_create_dataset",
    "build_mlflow_record",
    "write_to_mlflow_dataset",
]


def experiment_name_for(config: WorkflowConfig) -> str:
    experiment_name = config.mlflow_dataset.experiment_name if config.mlflow_dataset else None
    return _experiment_name_for(config.process_key, experiment_name)


def dataset_name_for(config: WorkflowConfig) -> str:
    name_override = config.mlflow_dataset.name if config.mlflow_dataset else None
    experiment_name = config.mlflow_dataset.experiment_name if config.mlflow_dataset else None
    return _dataset_name_for(config.process_key, name_override, experiment_name)


def tracking_uri_for(config: WorkflowConfig, repo_root: Path) -> str:
    tracking_uri_override = config.mlflow_dataset.tracking_uri if config.mlflow_dataset else None
    return _tracking_uri_for(tracking_uri_override, repo_root)


def build_mlflow_record(config: WorkflowConfig, agent_history: dict[str, Any]) -> dict[str, Any]:
    """Shape one completed run's agent-history report as an MLflow dataset record."""
    return _build_mlflow_record(
        process_key=config.process_key,
        process_instance_id=agent_history["processInstanceId"],
        agent_goal=agent_history["goal"],
        input_variables=agent_history["inputVariables"],
        tool_calls=agent_history["toolCalls"],
        iterations=agent_history["iterations"],
        final_output=agent_history["finalOutput"],
        available_tools=list(config.available_tools.values()),
        expected_tool_rules=config.expected_tools,
        dataset_path=config.dataset_path,
    )


def write_to_mlflow_dataset(
    config: WorkflowConfig,
    agent_history: dict[str, Any],
    repo_root: Path,
) -> tuple[str, str | None]:
    """Merge one record for ``agent_history`` into the configured MLflow dataset.

    Returns ``(dataset_name, dataset_record_id)`` — ``dataset_record_id`` is
    ``None`` if a record for this ``processInstanceId`` was already present
    (writes are idempotent; duplicate runs are skipped rather than re-written).
    """
    record = build_mlflow_record(config, agent_history)
    dataset_name, record_id, _written = _write_to_mlflow_dataset(
        tracking_uri=tracking_uri_for(config, repo_root),
        process_key=config.process_key,
        dataset_name=config.mlflow_dataset.name if config.mlflow_dataset else None,
        record=record,
        experiment_name=config.mlflow_dataset.experiment_name if config.mlflow_dataset else None,
    )
    return dataset_name, record_id

