"""Recommendation response models — content recommendations for a profile."""

from __future__ import annotations

from pydantic import BaseModel


class RecommendationResponse(BaseModel):
    """A single content recommendation targeting a discovered query (spec §4.2)."""

    recommendation_uuid: str
    target_query_uuid: str
    content_type: str
    title: str
    rationale: str
    target_keywords: list[str]
    priority: str


class RecommendationListResponse(BaseModel):
    """The set of recommendations from a profile's most recent run."""

    items: list[RecommendationResponse]
    count: int


__all__ = ["RecommendationListResponse", "RecommendationResponse"]
