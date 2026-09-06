"""Query response models — discovered sub-queries and their metrics."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class QueryResponse(BaseModel):
    """A single discovered query with its metrics and visibility (spec §4.2)."""

    query_uuid: str
    query_text: str
    estimated_search_volume: int
    competitive_difficulty: int
    opportunity_score: float
    domain_visible: bool
    visibility_position: int | None
    visibility_status: str
    discovered_at: datetime


class QueryListResponse(BaseModel):
    """A paginated list of queries, sorted by opportunity score (highest first)."""

    items: list[QueryResponse]
    page: int
    per_page: int
    total: int
    total_pages: int


__all__ = ["QueryListResponse", "QueryResponse"]
