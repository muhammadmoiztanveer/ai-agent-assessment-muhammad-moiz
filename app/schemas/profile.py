"""Profile request/response models — the public contract for profile endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProfileCreate(BaseModel):
    """Request body for ``POST /api/v1/profiles``.

    ``name`` and ``domain`` are required and must be non-blank; the rest are
    optional. Unknown fields are rejected so typos surface as ``422`` instead of
    being silently ignored.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255, description="Human-readable brand name.")
    domain: str = Field(
        min_length=1, max_length=255, description="Brand domain, e.g. surferseo.com."
    )
    industry: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    competitors: list[str] = Field(default_factory=list, description="Competitor domains/names.")


class ProfileCreatedResponse(BaseModel):
    """Response for a freshly created profile (HTTP 201)."""

    profile_uuid: str
    name: str
    domain: str
    industry: str | None
    description: str | None
    competitors: list[str]
    status: str = "created"
    created_at: datetime


class ProfileSummarySchema(BaseModel):
    """Aggregated summary statistics for a profile."""

    total_runs: int
    latest_run_status: str | None
    average_opportunity_score: float | None


class ProfileDetailResponse(BaseModel):
    """Response for ``GET /api/v1/profiles/{uuid}`` — profile plus summary stats."""

    profile_uuid: str
    name: str
    domain: str
    industry: str | None
    description: str | None
    competitors: list[str]
    created_at: datetime
    summary: ProfileSummarySchema


__all__ = [
    "ProfileCreate",
    "ProfileCreatedResponse",
    "ProfileDetailResponse",
    "ProfileSummarySchema",
]
