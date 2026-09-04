"""Configuration for the standalone Fluxnova automated-run service.

Deploy/deploy-and-start concerns only — no reporting or evaluation fields
(those live in the harness's ``WorkflowConfig``, read by ``mlflow-eval``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RunnerConfig:
    """All settings needed to deploy and start one workflow run."""

    fluxnova_url: str
    bpmn_path: Path
    process_key: str
    deployment_name: str
    subprocess_id: str | None = None
    variables: dict[str, Any] = field(default_factory=dict)
    mock_workers: dict[str, dict[str, Any]] = field(default_factory=dict)
    additional_bpmn_paths: list[Path] = field(default_factory=list)
    wait_for_activity: str | None = None

    @classmethod
    def from_file(cls, path: Path) -> RunnerConfig:
        """Load a workflow YAML config file.

        ``bpmn_path`` is resolved relative to the repo root if not absolute.
        Extra keys (e.g. ``available_tools``, ``mlflow_dataset`` — used by the
        harness's eval tools) are simply ignored, so the same YAML file used
        for evaluation config can be reused here unchanged.
        """
        root_dir = Path(__file__).resolve().parent.parent.parent.parent
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        bpmn_path = Path(raw["bpmn_path"])
        if not bpmn_path.is_absolute():
            bpmn_path = root_dir / bpmn_path

        def _resolve(p: str | Path) -> Path:
            resolved = Path(p)
            return resolved if resolved.is_absolute() else root_dir / resolved

        additional_bpmn_paths = [_resolve(p) for p in (raw.get("additional_bpmn_paths") or [])]
        return cls(
            fluxnova_url=raw["fluxnova_url"].rstrip("/"),
            bpmn_path=bpmn_path,
            process_key=raw["process_key"],
            deployment_name=raw.get("deployment_name"),
            subprocess_id=raw.get("subprocess_id"),
            variables=raw.get("variables") or {},
            mock_workers=raw.get("mock_workers") or {},
            additional_bpmn_paths=additional_bpmn_paths,
            wait_for_activity=raw.get("wait_for_activity"),
        )
