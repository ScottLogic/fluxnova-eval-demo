"""Eval endpoints: auto-eval (listener) sampling control, eval definitions, metrics/tracing.

The per-run "skip eval service worker" toggle needs no endpoint of its own —
`workflow.py`'s `POST /api/workflow/runs` already accepts arbitrary process
variable overrides, so the frontend just includes `skipEvalServiceWorker` in
that same request (see UI_PROPOSAL.md step 10). The BPMN gate lives in
`bpmn/LoanApprovalProcess_AI.bpmn`'s `Gateway_SkipEvalServiceWorker`, and its
default (false — auto-eval on) comes from
`fluxnova-runner/config/loan_approval_process_ai.yml`.

`auto-eval` (this file) is different: it controls the non-blocking Eval service
task (`ServiceTask_AsyncEvaluateAgentOutput`), which runs on every run. Its toggle
drives eval-trace-listener's live sample rate (see `ui_api.listener_client` /
`eval_trace_listener/control.py`): off sets it to 0.0, so the task completes
without scoring, and on sets it to 1.0, so every run is scored.

`definitions` (this file) exposes the complete set of scorers used anywhere in the
project, and where each one runs — read straight off the real scorer objects (see
`ui_api.eval_definitions`), so it can never drift out of sync with what executes.

Metrics/tracing is still empty — see UI_PROPOSAL.md step 15 for what fills that in.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ui_api import eval_definitions, listener_client

router = APIRouter(prefix="/api/evals", tags=["evals"])


class AutoEvalConfig(BaseModel):
    enabled: bool


@router.get("/auto-eval")
def get_auto_eval() -> AutoEvalConfig:
    try:
        rate = listener_client.get_sample_rate()
    except listener_client.ListenerControlError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return AutoEvalConfig(enabled=rate > 0.0)


@router.post("/auto-eval")
def set_auto_eval(config: AutoEvalConfig) -> AutoEvalConfig:
    try:
        rate = listener_client.set_sample_rate(1.0 if config.enabled else 0.0)
    except listener_client.ListenerControlError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return AutoEvalConfig(enabled=rate > 0.0)


@router.get("/definitions")
def get_definitions() -> dict[str, list[dict[str, Any]]]:
    return {"scorers": eval_definitions.all_scorers()}
