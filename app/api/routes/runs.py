"""Pipeline run routes: execute the full DAG for a profile and inspect runs.

``POST /profiles/{uuid}/run`` is the core endpoint. By default it executes
**synchronously** (a run may take 10-30s, which the spec accepts) and returns
HTTP 200. Passing ``?async=true`` uses the **async bonus** (spec §4.2): the run is
enqueued to a background worker and the endpoint returns HTTP 202 with
``status: "queued"`` immediately; the caller then polls
``GET /runs/{run_uuid}`` until the run reaches a terminal state.

A degraded run still returns HTTP 200 with ``status: partial``/``failed`` and
``error_flag: true`` rather than an HTTP error, so callers can inspect partial
results.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Response, status

from app.schemas.run import RunResponse
from app.services import pipeline_service

router = APIRouter(prefix="/api/v1/profiles", tags=["runs"])
runs_router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


@router.post(
    "/{profile_uuid}/run",
    response_model=RunResponse,
    summary="Run the full agentic pipeline for a profile",
)
def run_pipeline(
    profile_uuid: str,
    response: Response,
    async_: bool = Query(
        default=False,
        alias="async",
        description="Run in the background and return 202 immediately (poll GET /runs/{uuid}).",
    ),
    simulate: Literal["outage", "degraded"] | None = Query(
        default=None,
        description=(
            "Inject a deterministic dependency failure to demonstrate resilience: "
            "'outage' → all retrieval fails (run 'failed' via fallback); "
            "'degraded' → some calls fail (run 'partial'). Runs synchronously."
        ),
    ),
) -> RunResponse:
    """Run Planner → Retrieval → Extraction → Analysis → Report and persist it.

    Synchronous by default (200). With ``?async=true`` the run is queued and this
    returns 202 with ``status: "queued"``. ``?simulate=`` forces a synchronous run
    with an injected failure so the fallback/partial path can be shown live.
    """
    if simulate is not None:
        return pipeline_service.run_profile_pipeline(profile_uuid, simulate=simulate)
    if async_:
        result = pipeline_service.enqueue_profile_run(profile_uuid)
        response.status_code = status.HTTP_202_ACCEPTED
        return result
    return pipeline_service.run_profile_pipeline(profile_uuid)


@runs_router.get(
    "/{run_uuid}",
    response_model=RunResponse,
    summary="Get the status and result of a pipeline run",
)
def get_run(run_uuid: str) -> RunResponse:
    """Return a run's current status and (once finished) its full result.

    Works for both synchronous and asynchronous runs; poll this after an async
    ``POST /run?async=true`` until ``status`` is terminal.
    """
    return pipeline_service.get_run_response(run_uuid)


__all__ = ["router", "runs_router"]
