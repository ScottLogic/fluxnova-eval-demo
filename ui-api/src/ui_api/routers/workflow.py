"""Workflow-run endpoints: trigger a BPMN run, fetch run status.

Wraps `fluxnova_runner.client.Client`/`RunnerConfig` directly — see
`ui_api.workflow_runner` for why this doesn't need a subprocess like
`regression.py` does.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fluxnova_runner.client import ApiError

from ui_api import workflow_runner

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


@router.post("/runs", status_code=202)
def start_run(variable_overrides: dict[str, Any] | None = None) -> dict[str, str]:
    try:
        instance_id = workflow_runner.start_run(variable_overrides)
    except ApiError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"instanceId": instance_id}


@router.get("/runs/{instance_id}")
def get_run(instance_id: str) -> dict:
    try:
        return workflow_runner.get_run(instance_id)
    except ApiError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
