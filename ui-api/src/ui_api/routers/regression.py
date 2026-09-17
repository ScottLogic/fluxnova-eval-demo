"""Regression endpoints: list available tests, trigger a run, poll results.

Wraps `regression/test_mlflow_regression.py` as a subprocess rather than importing
it — see `ui_api.regression_runner` for why and how.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ui_api import regression_runner

router = APIRouter(prefix="/api/regression", tags=["regression"])


@router.get("/tests")
def list_tests() -> dict[str, list[str]]:
    return {"tests": regression_runner.list_tests()}


@router.post("/runs", status_code=202)
def start_run() -> dict[str, str]:
    run_id = regression_runner.start_run()
    return {"runId": run_id}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    result = regression_runner.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown run id: {run_id}")
    return result
