"""Eval endpoints: eval definitions, metrics/tracing.

The per-run "skip eval service worker" toggle needs no endpoint of its own —
`workflow.py`'s `POST /api/workflow/runs` already accepts arbitrary process
variable overrides, so the frontend just includes `skipEvalServiceWorker` in
that same request (see UI_PROPOSAL.md step 10). The BPMN gate lives in
`bpmn/LoanApprovalProcess_AI.bpmn`'s `Gateway_SkipEvalServiceWorker`, and its
default (false — guardrail on) comes from
`fluxnova-runner/config/loan_approval_process_ai.yml`.

The non-blocking Eval service task (`ServiceTask_AsyncEvaluateAgentOutput`,
served by eval-async-worker) always runs in the demo, so it has no toggle.

`definitions` (this file) exposes the complete set of scorers used anywhere in the
project, and where each one runs — read straight off the real scorer objects (see
`ui_api.eval_definitions`), so it can never drift out of sync with what executes.

Metrics/tracing is still empty — see UI_PROPOSAL.md step 15 for what fills that in.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ui_api import eval_definitions

router = APIRouter(prefix="/api/evals", tags=["evals"])


@router.get("/definitions")
def get_definitions() -> dict[str, list[dict[str, Any]]]:
    return {"scorers": eval_definitions.all_scorers()}
