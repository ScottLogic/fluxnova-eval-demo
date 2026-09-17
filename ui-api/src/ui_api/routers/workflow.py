"""Workflow-run endpoints: trigger a BPMN run, fetch run status.

Empty for now — see UI_PROPOSAL.md step 7 for the fluxnova-runner-backed
implementation.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/workflow", tags=["workflow"])
