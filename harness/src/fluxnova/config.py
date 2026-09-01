"""Configuration loaded from a YAML workflow config file."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

_SCHEMA_PATH = Path(__file__).parent / "workflow-config.schema.json"
_SCHEMA = None  # cached after first load


def _schema() -> dict:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA


# Matches:  $varName == "string"  |  $varName != true  |  $varName == 42
_IF_PATTERN = re.compile(
    r'^\$(?P<variable>\w+)\s*(?P<op>==|!=)\s*(?P<value>.+)$'
)


@dataclass
class ExpectedToolRule:
    """A single rule from the ``expected_tools`` config list.

    ``tool`` is the display name of the tool.
    ``if_expr`` is an optional GitLab-style condition string, e.g.
    ``'$applicantType == "EMPLOYED"'``.  When absent the tool is always
    expected.
    """

    tool: str
    if_expr: str | None = None

    def matches(self, input_variables: dict[str, Any]) -> bool:
        """Return True if this rule's condition is satisfied (or absent)."""
        if self.if_expr is None:
            return True
        m = _IF_PATTERN.match(self.if_expr.strip())
        if not m:
            raise ValueError(f"Cannot parse expected_tools if expression: {self.if_expr!r}")
        variable, op, raw_value = m.group("variable"), m.group("op"), m.group("value").strip()
        resolved = _coerce(raw_value)
        actual = input_variables.get(variable)
        if op == "==":
            return actual == resolved
        return actual != resolved  # !=


def _coerce(raw: str) -> Any:
    """Cast a raw YAML expression value to its Python equivalent."""
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    try:
        return int(raw)
    except ValueError:
        return raw



@dataclass
class MlflowDatasetConfig:
    """Settings controlling whether/how a run is recorded into an MLflow evaluation dataset."""

    enabled: bool = False
    name: str | None = None
    tracking_uri: str | None = None
    also_write_json_report: bool = True
    experiment_name: str | None = None


@dataclass
class WorkflowConfig:
    """All settings needed to deploy and start one workflow run."""

    fluxnova_url: str
    bpmn_path: Path
    process_key: str
    deployment_name: str
    subprocess_id: str | None = None
    variables: dict[str, Any] = field(default_factory=dict)
    mock_workers: dict[str, dict[str, Any]] = field(default_factory=dict)
    user_tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    available_tools: dict[str, str] = field(default_factory=dict)
    expected_tools: list[ExpectedToolRule] = field(default_factory=list)
    dataset_path: Path | None = None
    mlflow_dataset: MlflowDatasetConfig | None = None


    @classmethod
    def from_file(cls, path: Path) -> WorkflowConfig:
        """Load and validate a YAML config file.

        The ``bpmn_path`` value is resolved relative to the config file's
        directory if it is not absolute.
        """
        script_path = Path(__file__).resolve()
        root_dir = script_path.parent.parent.parent.parent
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        try:
            jsonschema.validate(instance=raw, schema=_schema())
        except jsonschema.ValidationError as exc:
            raise ValueError(f"Invalid workflow config {path}: {exc.message}") from exc
        bpmn_path = Path(raw["bpmn_path"])
        bpmn_path = root_dir / bpmn_path
        expected_tools = [
            ExpectedToolRule(tool=r["tool"], if_expr=r.get("if"))
            for r in (raw.get("expected_tools") or [])
        ]
        raw_dataset_path = raw.get("dataset_path")
        dataset_path = (root_dir / raw_dataset_path) if raw_dataset_path else None
        raw_mlflow_dataset = raw.get("mlflow_dataset")
        mlflow_dataset = (
            MlflowDatasetConfig(
                enabled=raw_mlflow_dataset.get("enabled", False),
                name=raw_mlflow_dataset.get("name"),
                tracking_uri=raw_mlflow_dataset.get("tracking_uri"),
                also_write_json_report=raw_mlflow_dataset.get("also_write_json_report", True),
                experiment_name=raw_mlflow_dataset.get("experiment_name"),
            )
            if raw_mlflow_dataset
            else None
        )
        return cls(
            fluxnova_url=raw["fluxnova_url"].rstrip("/"),
            bpmn_path=bpmn_path,
            process_key=raw["process_key"],
            variables=raw.get("variables") or {},
            deployment_name=raw.get("deployment_name"),
            subprocess_id=raw.get("subprocess_id"),
            mock_workers=raw.get("mock_workers") or {},
            user_tasks=raw.get("user_tasks") or {},
            available_tools=raw.get("available_tools") or {},
            expected_tools=expected_tools,
            dataset_path=dataset_path,
            mlflow_dataset=mlflow_dataset,
        )
