"""Recommendation route: list content recommendations for a profile."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.recommendation import RecommendationListResponse
from app.services import profile_service

router = APIRouter(prefix="/api/v1/profiles", tags=["recommendations"])


@router.get(
    "/{profile_uuid}/recommendations",
    response_model=RecommendationListResponse,
    summary="List content recommendations from a profile's most recent run",
)
def list_recommendations(profile_uuid: str) -> RecommendationListResponse:
    """Return the recommendations produced by the profile's latest run."""
    return profile_service.list_profile_recommendations(profile_uuid)


__all__ = ["router"]
