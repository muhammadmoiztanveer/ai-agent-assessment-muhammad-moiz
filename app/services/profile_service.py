"""Profile service — create profiles and read them with summary stats.

Keeps route handlers thin: each function owns its own short-lived transaction via
:func:`~app.db.database.session_scope` and returns a ready-to-serialize Pydantic
response model, so no detached-ORM concerns leak up to the API layer.
"""

from __future__ import annotations

from app.api.errors import NotFoundError
from app.db import repositories as repo
from app.db.database import session_scope
from app.db.models import VisibilityStatus
from app.db.repositories import QueryFilters
from app.schemas.profile import (
    ProfileCreate,
    ProfileCreatedResponse,
    ProfileDetailResponse,
    ProfileSummarySchema,
)
from app.schemas.query import QueryListResponse, QueryResponse
from app.schemas.recommendation import (
    RecommendationListResponse,
    RecommendationResponse,
)


def create_profile(payload: ProfileCreate) -> ProfileCreatedResponse:
    """Persist a new profile and return its created representation."""
    with session_scope() as session:
        profile = repo.create_profile(
            session,
            name=payload.name,
            domain=payload.domain,
            industry=payload.industry,
            description=payload.description,
            competitors=payload.competitors,
        )
        return ProfileCreatedResponse(
            profile_uuid=profile.profile_uuid,
            name=profile.name,
            domain=profile.domain,
            industry=profile.industry,
            description=profile.description,
            competitors=list(profile.competitors),
            status="created",
            created_at=profile.created_at,
        )


def get_profile_detail(profile_uuid: str) -> ProfileDetailResponse:
    """Return a profile plus its summary stats, or raise :class:`NotFoundError`."""
    with session_scope() as session:
        profile = repo.get_profile(session, profile_uuid)
        if profile is None:
            raise NotFoundError(f"Profile '{profile_uuid}' not found.")

        summary = repo.profile_summary(session, profile_uuid)
        return ProfileDetailResponse(
            profile_uuid=profile.profile_uuid,
            name=profile.name,
            domain=profile.domain,
            industry=profile.industry,
            description=profile.description,
            competitors=list(profile.competitors),
            created_at=profile.created_at,
            summary=ProfileSummarySchema(
                total_runs=summary.total_runs,
                latest_run_status=(
                    summary.latest_run_status.value
                    if summary.latest_run_status is not None
                    else None
                ),
                average_opportunity_score=summary.average_opportunity_score,
            ),
        )


def list_profile_queries(
    profile_uuid: str,
    *,
    min_score: float | None = None,
    status: VisibilityStatus | None = None,
    page: int = 1,
    per_page: int = 20,
) -> QueryListResponse:
    """List the most recent run's queries for a profile (filtered + paginated).

    Queries come from the profile's latest run, sorted by opportunity score
    (highest first). An unknown profile raises :class:`NotFoundError`; a profile
    with no runs returns an empty page.
    """
    with session_scope() as session:
        profile = repo.get_profile(session, profile_uuid)
        if profile is None:
            raise NotFoundError(f"Profile '{profile_uuid}' not found.")

        latest = repo.latest_run_for_profile(session, profile_uuid)
        if latest is None:
            return QueryListResponse(items=[], page=page, per_page=per_page, total=0, total_pages=0)

        result = repo.queries_for_run(
            session,
            latest.run_uuid,
            QueryFilters(min_score=min_score, status=status, page=page, per_page=per_page),
        )
        return QueryListResponse(
            items=[_query_response(q) for q in result.items],
            page=result.page,
            per_page=result.per_page,
            total=result.total,
            total_pages=result.total_pages,
        )


def list_profile_recommendations(profile_uuid: str) -> RecommendationListResponse:
    """List content recommendations from a profile's most recent run."""
    with session_scope() as session:
        profile = repo.get_profile(session, profile_uuid)
        if profile is None:
            raise NotFoundError(f"Profile '{profile_uuid}' not found.")

        recs = repo.recommendations_for_profile_latest_run(session, profile_uuid)
        items = [_recommendation_response(r) for r in recs]
        return RecommendationListResponse(items=items, count=len(items))


def _query_response(query: repo.Query) -> QueryResponse:
    """Map a Query ORM row to its response model."""
    return QueryResponse(
        query_uuid=query.query_uuid,
        query_text=query.query_text,
        estimated_search_volume=query.estimated_search_volume,
        competitive_difficulty=query.competitive_difficulty,
        opportunity_score=query.opportunity_score,
        domain_visible=query.domain_visible,
        visibility_position=query.visibility_position,
        visibility_status=query.visibility_status.value,
        discovered_at=query.discovered_at,
    )


def _recommendation_response(rec: repo.Recommendation) -> RecommendationResponse:
    """Map a Recommendation ORM row to its response model."""
    return RecommendationResponse(
        recommendation_uuid=rec.recommendation_uuid,
        target_query_uuid=rec.target_query_uuid,
        content_type=rec.content_type.value,
        title=rec.title,
        rationale=rec.rationale,
        target_keywords=list(rec.target_keywords),
        priority=rec.priority.value,
    )


__all__ = [
    "create_profile",
    "get_profile_detail",
    "list_profile_queries",
    "list_profile_recommendations",
]
