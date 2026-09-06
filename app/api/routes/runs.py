"""Pipeline run route: execute the full DAG for a profile.

This is the core endpoint. Execution is synchronous (a run may take 10-30s, which
the spec accepts). A degraded run still returns HTTP 200 with ``status: partial``
or ``failed`` and ``error_flag: true`` rather than an HTTP error, so callers can
inspect partial results.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.run import RunResponse
from app.services import pipeline_service

router = APIRouter(prefix="/api/v1/profiles", tags=["runs"])


@router.post(
    "/{profile_uuid}/run",
    response_model=RunResponse,
    summary="Run the full agentic pipeline for a profile",
)
def run_pipeline(profile_uuid: str) -> RunResponse:
    """Run Planner → Retrieval → Extraction → Analysis → Report and persist it."""
    return pipeline_service.run_profile_pipeline(profile_uuid)


__all__ = ["router"]
