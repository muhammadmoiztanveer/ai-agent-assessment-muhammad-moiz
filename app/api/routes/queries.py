"""Query routes: list a profile's discovered queries, and recheck a single query."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.db.models import VisibilityStatus
from app.schemas.query import QueryListResponse
from app.schemas.run import RecheckResponse
from app.services import profile_service, recheck_service

router = APIRouter(prefix="/api/v1", tags=["queries"])


@router.get(
    "/profiles/{profile_uuid}/queries",
    response_model=QueryListResponse,
    summary="List discovered queries for a profile's most recent run",
)
def list_queries(
    profile_uuid: str,
    min_score: Annotated[
        float | None, Query(ge=0.0, le=1.0, description="Minimum opportunity score.")
    ] = None,
    status: Annotated[
        VisibilityStatus | None, Query(description="Filter by visibility status.")
    ] = None,
    page: Annotated[int, Query(ge=1, description="1-based page number.")] = 1,
    per_page: Annotated[int, Query(ge=1, le=100, description="Items per page (max 100).")] = 20,
) -> QueryListResponse:
    """Return queries sorted by opportunity score (highest first), filtered + paged."""
    return profile_service.list_profile_queries(
        profile_uuid,
        min_score=min_score,
        status=status,
        page=page,
        per_page=per_page,
    )


@router.post(
    "/queries/{query_uuid}/recheck",
    response_model=RecheckResponse,
    summary="Re-run retrieval + extraction + analysis for a single query",
)
def recheck_query(query_uuid: str) -> RecheckResponse:
    """Refresh one query's metrics and recommendations, returning the updated data."""
    return recheck_service.recheck_query(query_uuid)


__all__ = ["router"]
