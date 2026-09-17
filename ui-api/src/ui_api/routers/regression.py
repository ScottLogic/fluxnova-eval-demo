"""Regression endpoints: list available tests, trigger a run, poll results.

Empty for now — see UI_PROPOSAL.md step 5 for the pytest --json-report-backed
implementation.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/regression", tags=["regression"])
