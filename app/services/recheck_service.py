"""Recheck service — re-run Retrieval + Extraction + Analysis for one query.

Backs ``POST /api/v1/queries/{query_uuid}/recheck``. It reuses the exact same
agents as a full run, but scopes the work to a single query: it builds a small,
single-keyword retrieval plan, executes it, normalizes and analyzes the result,
then updates the stored query's metrics and regenerates its recommendations.

This is useful after a fallback/partial run or after the user publishes content —
it refreshes one query without paying for a whole pipeline run.
"""

from __future__ import annotations

from collections.abc import Collection

from app.agents.types import (
    Insight,
    PlannedCall,
    ProfileContext,
    RetrievalPlan,
)
from app.api.errors import NotFoundError
from app.db import repositories as repo
from app.db.database import session_scope
from app.db.models import Profile
from app.graph.dependencies import build_dependencies
from app.observability.logging import get_logger
from app.observability.tracing import correlation_context, new_correlation_id
from app.schemas.query import QueryResponse
from app.schemas.recommendation import RecommendationResponse
from app.schemas.run import RecheckResponse

_logger = get_logger("service.recheck")


def _profile_context(profile: Profile) -> ProfileContext:
    return ProfileContext(
        name=profile.name,
        domain=profile.domain,
        industry=profile.industry,
        description=profile.description,
        competitors=tuple(profile.competitors or ()),
    )


def _single_query_plan(question: str, brand: str, tools: Collection[str]) -> RetrievalPlan:
    """Build a retrieval plan that probes a single keyword across all endpoints."""
    calls: list[PlannedCall] = []
    if "keyword_metrics" in tools:
        calls.append(
            PlannedCall(
                tool="keyword_metrics",
                args={"keywords": [question]},
                rationale="Refresh search demand and difficulty for the query.",
            )
        )
    if "serp_organic_search" in tools:
        calls.append(
            PlannedCall(
                tool="serp_organic_search",
                args={"keyword": question},
                rationale="Re-check organic search visibility for the query.",
            )
        )
    if "ai_overview_search" in tools:
        calls.append(
            PlannedCall(
                tool="ai_overview_search",
                args={"keyword": question},
                rationale="Re-check AI Overview visibility for the query.",
            )
        )
    if "llm_visibility_lookup" in tools:
        calls.append(
            PlannedCall(
                tool="llm_visibility_lookup",
                args={"prompt": question, "brand": brand},
                rationale="Re-check whether the brand is cited in LLM answers.",
            )
        )
    return RetrievalPlan(research_question=question, calls=tuple(calls))


def _pick_insight(insights: tuple[Insight, ...], query_text: str) -> Insight | None:
    """Return the insight matching the rechecked query, preferring an exact match."""
    key = query_text.strip().lower()
    for insight in insights:
        if insight.query_text.strip().lower() == key:
            return insight
    return insights[0] if insights else None


def recheck_query(query_uuid: str) -> RecheckResponse:
    """Re-run retrieval → extraction → analysis for a single query and update it."""
    # 1. Load the query and its profile (short read).
    with session_scope() as session:
        query = repo.get_query(session, query_uuid)
        if query is None:
            raise NotFoundError(f"Query '{query_uuid}' not found.")
        profile = repo.get_profile(session, query.profile_uuid)
        if profile is None:  # pragma: no cover - FK guarantees this
            raise NotFoundError(f"Profile '{query.profile_uuid}' not found.")
        context = _profile_context(profile)
        query_text = query.query_text
        run_uuid = query.run_uuid

    # 2. Run the scoped sub-pipeline outside any transaction.
    correlation_id = new_correlation_id()
    deps = build_dependencies()
    with correlation_context(correlation_id):
        _logger.info("service.recheck.start", query=query_text)
        plan = _single_query_plan(query_text, context.name, deps.tools.keys())
        outcome = deps.retrieval.run(plan)
        normalized = deps.extraction.run(outcome.results, context)
        analysis = deps.analysis.run(normalized, context)

    insight = _pick_insight(analysis.insights, query_text)
    usable = outcome.has_usable_results and insight is not None
    status = "completed" if usable else "partial"

    # 3. Update the query row and replace its recommendations.
    with session_scope() as session:
        query = repo.get_query(session, query_uuid)
        if query is None:  # pragma: no cover - deleted mid-recheck
            raise NotFoundError(f"Query '{query_uuid}' not found.")

        if insight is not None:
            repo.update_query_metrics(
                session,
                query,
                estimated_search_volume=insight.estimated_search_volume,
                competitive_difficulty=insight.competitive_difficulty,
                opportunity_score=insight.opportunity_score,
                domain_visible=insight.domain_visible,
                visibility_position=insight.visibility_position,
                visibility_status=insight.visibility_status,
            )

        repo.delete_recommendations_for_query(session, query_uuid)
        rec_responses: list[RecommendationResponse] = []
        for rec in analysis.recommendations:
            if rec.target_query_text.strip().lower() != query_text.strip().lower():
                continue
            saved = repo.add_recommendation(
                session,
                run_uuid=run_uuid,
                target_query_uuid=query_uuid,
                content_type=rec.content_type,
                title=rec.title,
                rationale=rec.rationale,
                target_keywords=list(rec.target_keywords),
                priority=rec.priority,
            )
            rec_responses.append(
                RecommendationResponse(
                    recommendation_uuid=saved.recommendation_uuid,
                    target_query_uuid=saved.target_query_uuid,
                    content_type=saved.content_type.value,
                    title=saved.title,
                    rationale=saved.rationale,
                    target_keywords=list(saved.target_keywords),
                    priority=saved.priority.value,
                )
            )

        query_response = QueryResponse(
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

    _logger.info("service.recheck.done", query=query_text, status=status, recs=len(rec_responses))
    return RecheckResponse(
        query=query_response,
        recommendations=rec_responses,
        status=status,
        correlation_id=correlation_id,
    )


__all__ = ["recheck_query"]
