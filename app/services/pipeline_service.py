"""Pipeline service — run the full DAG for a profile and persist the results.

This is the heart of ``POST /api/v1/profiles/{uuid}/run``. It:

1. loads the profile and builds the agent-facing :class:`ProfileContext`,
2. runs the compiled LangGraph pipeline **outside** any DB transaction (a run can
   take 10-30s, so no connection is held open while agents work),
3. persists the run, its discovered queries, and its recommendations in a short
   final transaction, and
4. returns a fully-serialized :class:`RunResponse`.

Discovered queries are persisted from the Analysis agent's ranked insights (which
already carry the opportunity score and visibility), and each recommendation is
linked to its target query by matching ``query_text``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agents.types import AnalysisResult, ProfileContext
from app.api.errors import NotFoundError
from app.db import repositories as repo
from app.db.database import session_scope
from app.db.models import Profile, RunStatus
from app.graph.build import run_pipeline
from app.graph.state import PipelineState
from app.observability.logging import get_logger
from app.schemas.run import InsightSchema, ReportSchema, RunResponse

_logger = get_logger("service.pipeline")

# How many top insights to surface in the run response and store on the run row.
_TOP_INSIGHTS = 5


def _profile_context(profile: Profile) -> ProfileContext:
    """Build the agent-facing profile context from a persisted profile."""
    return ProfileContext(
        name=profile.name,
        domain=profile.domain,
        industry=profile.industry,
        description=profile.description,
        competitors=tuple(profile.competitors or ()),
    )


def _research_question(profile: Profile) -> str:
    """Compose the research question the pipeline answers for a profile."""
    industry = f" within the {profile.industry} industry" if profile.industry else ""
    return (
        f"How does {profile.name} ({profile.domain}) show up in AI answers and "
        f"search results{industry}, and where are the biggest visibility opportunities?"
    )


def run_profile_pipeline(profile_uuid: str) -> RunResponse:
    """Execute the pipeline for a profile and persist + return the run."""
    # 1. Load the profile (short read) and capture what the run needs.
    with session_scope() as session:
        profile = repo.get_profile(session, profile_uuid)
        if profile is None:
            raise NotFoundError(f"Profile '{profile_uuid}' not found.")
        context = _profile_context(profile)
        research_question = _research_question(profile)

    # 2. Run the DAG with no DB transaction held open.
    state = run_pipeline(profile=context, research_question=research_question)

    # 3. Persist the run + queries + recommendations, then build the response.
    with session_scope() as session:
        return _persist_run(session, profile_uuid=profile_uuid, state=state)


def _persist_run(session: Session, *, profile_uuid: str, state: PipelineState) -> RunResponse:
    """Write the run, its queries, and its recommendations; return the response."""
    status_value = state.get("status", "failed")
    correlation_id = state.get("correlation_id", "")
    error_flag = bool(state.get("error_flag", False))
    degraded_reason = state.get("degraded_reason")
    total_tokens = state.get("total_tokens")

    analysis: AnalysisResult | None = state.get("analysis")
    insights = list(analysis.insights) if analysis else []
    recommendations = list(analysis.recommendations) if analysis else []
    report = state.get("report")
    report_json = report.report_json if report else {}
    report_summary = report.report_summary if report else ""
    top_insights = insights[:_TOP_INSIGHTS]

    run = repo.create_run(
        session,
        profile_uuid=profile_uuid,
        correlation_id=correlation_id,
        status=RunStatus(status_value),
    )
    run.planned_retrieval_calls = int(state.get("planned_call_count", 0))
    run.extracted_records = int(state.get("extracted_count", 0))
    run.total_tokens = total_tokens
    run.error_flag = error_flag
    run.error_detail = {"degraded_reason": degraded_reason} if degraded_reason else None
    run.report_json = report_json
    run.report_summary = report_summary
    run.top_insights = [i.as_dict() for i in top_insights]
    run.finished_at = datetime.now(UTC)
    session.flush()

    # Persist every discovered query (from ranked insights) and index by text so
    # recommendations can be linked to their target query.
    text_to_query_uuid: dict[str, str] = {}
    for insight in insights:
        query = repo.add_query(
            session,
            run_uuid=run.run_uuid,
            profile_uuid=profile_uuid,
            query_text=insight.query_text,
            estimated_search_volume=insight.estimated_search_volume,
            competitive_difficulty=insight.competitive_difficulty,
            opportunity_score=insight.opportunity_score,
            domain_visible=insight.domain_visible,
            visibility_position=insight.visibility_position,
            visibility_status=insight.visibility_status,
        )
        text_to_query_uuid[insight.query_text.strip().lower()] = query.query_uuid

    for rec in recommendations:
        target_uuid = text_to_query_uuid.get(rec.target_query_text.strip().lower())
        if target_uuid is None:
            # A recommendation with no matching persisted query is skipped rather
            # than orphaned; this should not happen on the happy path.
            _logger.warning("service.pipeline.orphan_recommendation", target=rec.target_query_text)
            continue
        repo.add_recommendation(
            session,
            run_uuid=run.run_uuid,
            target_query_uuid=target_uuid,
            content_type=rec.content_type,
            title=rec.title,
            rationale=rec.rationale,
            target_keywords=list(rec.target_keywords),
            priority=rec.priority,
        )

    _logger.info(
        "service.pipeline.persisted",
        run_uuid=run.run_uuid,
        status=status_value,
        queries=len(insights),
        recommendations=len(recommendations),
    )

    return RunResponse(
        run_uuid=run.run_uuid,
        profile_uuid=profile_uuid,
        status=status_value,
        planned_retrieval_calls=run.planned_retrieval_calls,
        extracted_records=run.extracted_records,
        top_insights=[
            InsightSchema(
                query_text=i.query_text,
                opportunity_score=i.opportunity_score,
                estimated_search_volume=i.estimated_search_volume,
                competitive_difficulty=i.competitive_difficulty,
                domain_visible=i.domain_visible,
                visibility_position=i.visibility_position,
                visibility_status=i.visibility_status.value,
                rationale=i.rationale,
            )
            for i in top_insights
        ],
        report=ReportSchema(report_json=report_json, report_summary=report_summary),
        total_tokens=total_tokens,
        error_flag=error_flag,
        degraded_reason=degraded_reason,
        correlation_id=correlation_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


__all__ = ["run_profile_pipeline"]
