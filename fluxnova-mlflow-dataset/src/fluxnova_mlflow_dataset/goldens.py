"""Golden-scenario lookup for matching a run against its expected outcome."""

from __future__ import annotations

import json
from pathlib import Path


def load_goldens(dataset_path: Path | None) -> list[dict]:
    """Load the goldens JSON file, or return ``[]`` if none is configured."""
    if not dataset_path:
        return []
    return json.loads(Path(dataset_path).read_text(encoding="utf-8"))


def match_golden(goldens: list[dict], input_variables: dict) -> dict | None:
    """Return the first golden whose ``additional_metadata`` conditions all match
    the current run's ``input_variables`` (matched on applicantType/hasCollateral).
    """
    match_keys = ("applicantType", "hasCollateral")
    for golden in goldens:
        meta = golden.get("additional_metadata") or {}
        if all(input_variables.get(k) == meta[k] for k in match_keys if k in meta):
            return golden
    return None
