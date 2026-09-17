"""Eval endpoints: per-run toggles, eval definitions, metrics/tracing.

Empty for now — see UI_PROPOSAL.md steps 8, 10 and 12.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/evals", tags=["evals"])
