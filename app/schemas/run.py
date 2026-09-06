"""Run + recheck response models — the core pipeline endpoint contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.query import QueryResponse
from app.schemas.recommendation import RecommendationResponse


class InsightSchema(BaseModel):
    """A scored, ranked query surfaced in the run's top insights (spec §4.2)."""

    query_text: str
    opportunity_score: float
    estimated_search_volume: int
    competitive_difficulty: int
    domain_visible: bool
    visibility_position: int | None
    visibility_status: str
    rationale: str


class ReportSchema(BaseModel):
    """The final deliverable: structured JSON plus a human-readable summary."""

    report_json: dict[str, Any]
    report_summary: str


class NodeMetricSchema(BaseModel):
    """Observability for a single executed DAG node (spec §3.6)."""

    node: str
    duration_ms: float
    success: bool
    retry_count: int
    api_calls: int
    error_code: str | None = None


class ObservabilitySchema(BaseModel):
    """Per-run trace + metrics summary surfaced for inspection (spec §3.6).

    Mirrors :meth:`app.observability.metrics.RunMetrics.summary` so the exact
    node-by-node trace, latencies, retry counts, API-call totals, and token usage
    that are logged during a run are also queryable through the API (and rendered
    by the dashboard).
    """

    correlation_id: str
    total_duration_ms: float
    node_count: int
    success_count: int
    failure_count: int
    success_rate: float
    total_api_calls: int
    total_retries: int
    total_tokens: int
    nodes: list[NodeMetricSchema]


class RunResponse(BaseModel):
    """Response for ``POST /api/v1/profiles/{uuid}/run`` (spec §4.2).

    Carries the run identity and status, the Planner's planned call count, the
    number of normalized records, the top scored insights, the final report, the
    total LLM tokens used, and the correlation id that ties the run to its logs.
    """

    run_uuid: str
    profile_uuid: str
    status: str
    planned_retrieval_calls: int
    extracted_records: int
    top_insights: list[InsightSchema]
    report: ReportSchema
    total_tokens: int | None
    error_flag: bool
    degraded_reason: str | None
    correlation_id: str
    started_at: datetime
    finished_at: datetime | None
    observability: ObservabilitySchema | None = None


class RecheckResponse(BaseModel):
    """Response for ``POST /api/v1/queries/{uuid}/recheck`` — updated single query."""

    query: QueryResponse
    recommendations: list[RecommendationResponse]
    status: str
    correlation_id: str


__all__ = [
    "InsightSchema",
    "NodeMetricSchema",
    "ObservabilitySchema",
    "RecheckResponse",
    "ReportSchema",
    "RunResponse",
]
