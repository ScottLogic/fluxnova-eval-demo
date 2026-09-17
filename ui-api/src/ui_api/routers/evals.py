"""Eval endpoints: eval definitions, metrics/tracing.

The per-run "skip eval service worker" toggle needs no endpoint of its own —
`workflow.py`'s `POST /api/workflow/runs` already accepts arbitrary process
variable overrides, so the frontend just includes `skipEvalServiceWorker` in
that same request (see UI_PROPOSAL.md step 10). The BPMN gate lives in
`bpmn/LoanApprovalProcess_AI.bpmn`'s `Gateway_SkipEvalServiceWorker`, and its
default (false — auto-eval on) comes from
`fluxnova-runner/config/loan_approval_process_ai.yml`.

Empty for now — see UI_PROPOSAL.md steps 11 and 13 for what fills this in.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/evals", tags=["evals"])
