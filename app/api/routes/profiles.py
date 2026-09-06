"""Profile routes: create a profile, and read it with summary stats."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.schemas.profile import ProfileCreate, ProfileCreatedResponse, ProfileDetailResponse
from app.services import profile_service

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])


@router.post(
    "",
    response_model=ProfileCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a brand/keyword profile",
)
def create_profile(payload: ProfileCreate) -> ProfileCreatedResponse:
    """Create a profile and return it with ``status: created`` (HTTP 201)."""
    return profile_service.create_profile(payload)


@router.get(
    "/{profile_uuid}",
    response_model=ProfileDetailResponse,
    summary="Get a profile plus summary stats",
)
def get_profile(profile_uuid: str) -> ProfileDetailResponse:
    """Return a profile with total runs, latest run status, and average score."""
    return profile_service.get_profile_detail(profile_uuid)


__all__ = ["router"]
