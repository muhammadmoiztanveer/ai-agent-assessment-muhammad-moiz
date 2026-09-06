"""Pipeline service — run the full DAG for a profile and persist the results.

This is the heart of ``POST /api/v1/profiles/{uuid}/run``. It supports two
execution modes over the same core logic:

* **Synchronous** (:func:`run_profile_pipeline`, the spec's core behaviour): create
  the run row, execute the DAG inline, persist, and return the completed run.
* **Asynchronous** (:func:`enqueue_profile_run` + :func:`execute_run`, the spec
  §4.2 bonus): create a ``queued`` run row, hand it to the background task queue,
  and return immediately; a worker later transitions it to ``running`` and then a
  terminal state. Callers poll :func:`get_run_response` via ``GET /runs/{uuid}``.

In both modes the DAG runs **outside** any DB transaction (a run can take 10-30s,
so no connection is held while agents work), and the run/queries/recommendations
are persisted in a short final transaction. Discovered queries come from the
Analysis agent's ranked insights; each recommendation is linked to its target
query by matching ``query_text``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from sqlalchemy.orm import Session

from app.agents.types import AnalysisResult, ProfileContext
from app.api.errors import NotFoundError
from app.db import repositories as repo
from app.db.database import session_scope
from app.db.models import Profile, Run, RunStatus
from app.graph.build import run_pipeline
from app.graph.state import PipelineState
from app.integrations.dataforseo.client import MockHook
from app.observability.logging import get_logger
from app.observability.tracing import new_correlation_id
from app.schemas.run import (
    InsightSchema,
    NodeMetricSchema,
    ObservabilitySchema,
    ReportSchema,
    RunResponse,
)

# Failure-simulation modes exposed via ``POST /run?simulate=...`` (demo + tests).
SimulateMode = Literal["outage", "degraded"]

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


# --------------------------------------------------------------------------- #
# Public entrypoints
# --------------------------------------------------------------------------- #
def _simulate_hook(mode: SimulateMode) -> MockHook:
    """Build a deterministic fault-injection hook for a simulation mode.

    - ``outage``: every retrieval call fails → all retries exhausted → the graph
      routes to ``fallback`` and the run ends ``failed`` (no crash).
    - ``degraded``: only the SERP-family calls fail while others succeed → some
      usable data survives → the run ends ``partial`` with an error flag.
    """

    def hook(path: str, _payload: dict[str, Any]) -> None:
        if mode == "outage":
            raise httpx.ConnectTimeout("simulated dependency outage")
        if "/serp/" in path:  # degraded: fail SERP endpoints only
            raise httpx.ConnectTimeout("simulated partial outage (serp)")

    return hook


def run_profile_pipeline(profile_uuid: str, *, simulate: SimulateMode | None = None) -> RunResponse:
    """Execute the pipeline synchronously and persist + return the run.

    ``simulate`` injects a deterministic dependency failure so the resilience /
    fallback behaviour can be demonstrated live from the API or dashboard.
    """
    correlation_id = new_correlation_id()

    # 1. Load the profile (short read) and create the run row up front so it is
    #    always inspectable, even mid-flight.
    with session_scope() as session:
        profile = _require_profile(session, profile_uuid)
        context = _profile_context(profile)
        research_question = _research_question(profile)
        run = repo.create_run(
            session,
            profile_uuid=profile_uuid,
            correlation_id=correlation_id,
            status=RunStatus.RUNNING,
        )
        run_uuid = run.run_uuid

    # 2. Run the DAG with no DB transaction held open.
    state = run_pipeline(
        profile=context,
        research_question=research_question,
        correlation_id=correlation_id,
        mock_hook=_simulate_hook(simulate) if simulate else None,
    )

    # 3. Persist results into the run row and return the response.
    with session_scope() as session:
        run = _require_run(session, run_uuid)
        _apply_state_to_run(session, run, state)
        return _run_to_response(run)


def enqueue_profile_run(profile_uuid: str) -> RunResponse:
    """Create a ``queued`` run and hand it to the background queue (async bonus).

    Returns immediately with the queued run so the caller can poll
    ``GET /api/v1/runs/{run_uuid}`` for progress and the final result.
    """
    # Import here to avoid an import cycle (run_queue lazily imports this module).
    from app.services.run_queue import get_run_queue

    correlation_id = new_correlation_id()
    with session_scope() as session:
        _require_profile(session, profile_uuid)  # 404 before we enqueue anything
        run = repo.create_run(
            session,
            profile_uuid=profile_uuid,
            correlation_id=correlation_id,
            status=RunStatus.QUEUED,
        )
        run_uuid = run.run_uuid
        response = _run_to_response(run)

    get_run_queue().submit(run_uuid)
    _logger.info("service.pipeline.enqueued", run_uuid=run_uuid, profile_uuid=profile_uuid)
    return response


def execute_run(run_uuid: str) -> None:
    """Background worker body: execute a queued run to a terminal state.

    Owns its own DB sessions (it runs in a worker thread) and always records a
    terminal status — even on unexpected failure — so a polling client never sees
    a run wedged in ``running``.
    """
    # 1. Transition queued → running and capture what the DAG needs.
    try:
        with session_scope() as session:
            run = repo.get_run(session, run_uuid)
            if run is None:  # pragma: no cover - defensive
                _logger.warning("service.pipeline.execute_missing_run", run_uuid=run_uuid)
                return
            profile = repo.get_profile(session, run.profile_uuid)
            if profile is None:  # pragma: no cover - FK guarantees this
                _mark_failed(session, run, "profile no longer exists")
                return
            run.status = RunStatus.RUNNING
            context = _profile_context(profile)
            research_question = _research_question(profile)
            correlation_id = run.correlation_id
    except Exception:  # pragma: no cover - defensive
        _logger.exception("service.pipeline.execute_setup_failed", run_uuid=run_uuid)
        return

    # 2. Run the DAG outside any transaction.
    try:
        state = run_pipeline(
            profile=context,
            research_question=research_question,
            correlation_id=correlation_id,
        )
    except Exception as exc:  # pragma: no cover - the graph itself degrades, not raises
        _logger.exception("service.pipeline.execute_dag_failed", run_uuid=run_uuid)
        with session_scope() as session:
            run = repo.get_run(session, run_uuid)
            if run is not None:
                _mark_failed(session, run, f"pipeline crashed: {type(exc).__name__}")
        return

    # 3. Persist results.
    with session_scope() as session:
        run = repo.get_run(session, run_uuid)
        if run is None:  # pragma: no cover - deleted mid-run
            return
        _apply_state_to_run(session, run, state)
    _logger.info("service.pipeline.executed", run_uuid=run_uuid, status=state.get("status"))


def get_run_response(run_uuid: str) -> RunResponse:
    """Return the current state of a run (any status) as a :class:`RunResponse`."""
    with session_scope() as session:
        run = _require_run(session, run_uuid)
        return _run_to_response(run)


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _require_profile(session: Session, profile_uuid: str) -> Profile:
    profile = repo.get_profile(session, profile_uuid)
    if profile is None:
        raise NotFoundError(f"Profile '{profile_uuid}' not found.")
    return profile


def _require_run(session: Session, run_uuid: str) -> Run:
    run = repo.get_run(session, run_uuid)
    if run is None:
        raise NotFoundError(f"Run '{run_uuid}' not found.")
    return run


def _mark_failed(session: Session, run: Run, reason: str) -> None:
    """Force a run into the ``failed`` terminal state with a reason."""
    run.status = RunStatus.FAILED
    run.error_flag = True
    run.error_detail = {"degraded_reason": reason}
    run.finished_at = datetime.now(UTC)
    session.flush()


def _apply_state_to_run(session: Session, run: Run, state: PipelineState) -> None:
    """Populate an existing run row + its queries + recommendations from state."""
    status_value = state.get("status", "failed")
    error_flag = bool(state.get("error_flag", False))
    degraded_reason = state.get("degraded_reason")

    analysis: AnalysisResult | None = state.get("analysis")
    insights = list(analysis.insights) if analysis else []
    recommendations = list(analysis.recommendations) if analysis else []
    report = state.get("report")
    report_json = report.report_json if report else {}
    report_summary = report.report_summary if report else ""
    top_insights = insights[:_TOP_INSIGHTS]

    run.status = RunStatus(status_value)
    run.planned_retrieval_calls = int(state.get("planned_call_count", 0))
    run.extracted_records = int(state.get("extracted_count", 0))
    run.total_tokens = state.get("total_tokens")
    run.error_flag = error_flag
    run.error_detail = {"degraded_reason": degraded_reason} if degraded_reason else None
    run.report_json = report_json
    run.report_summary = report_summary
    run.top_insights = [i.as_dict() for i in top_insights]
    # Persist the per-run observability trace/metrics so a finished run can be
    # inspected node-by-node through the API (and rendered by the dashboard).
    metrics = state.get("metrics")
    run.metrics = metrics.summary() if metrics is not None else None
    run.finished_at = datetime.now(UTC)
    session.flush()

    # Persist every discovered query (from ranked insights) and index by text so
    # recommendations can be linked to their target query.
    text_to_query_uuid: dict[str, str] = {}
    for insight in insights:
        query = repo.add_query(
            session,
            run_uuid=run.run_uuid,
            profile_uuid=run.profile_uuid,
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


def _run_to_response(run: Run) -> RunResponse:
    """Serialize a run row (any status) into a :class:`RunResponse`.

    A single serialization path used by the sync run, the async enqueue response,
    and the ``GET /runs/{uuid}`` poll — so every surface reports runs identically.
    """
    degraded_reason = (run.error_detail or {}).get("degraded_reason")
    top_insights = [
        InsightSchema(
            query_text=str(i.get("query_text", "")),
            opportunity_score=float(i.get("opportunity_score", 0.0)),
            estimated_search_volume=int(i.get("estimated_search_volume", 0)),
            competitive_difficulty=int(i.get("competitive_difficulty", 0)),
            domain_visible=bool(i.get("domain_visible", False)),
            visibility_position=i.get("visibility_position"),
            visibility_status=str(i.get("visibility_status", "unknown")),
            rationale=str(i.get("rationale", "")),
        )
        for i in (run.top_insights or [])
    ]
    return RunResponse(
        run_uuid=run.run_uuid,
        profile_uuid=run.profile_uuid,
        status=run.status.value,
        planned_retrieval_calls=run.planned_retrieval_calls,
        extracted_records=run.extracted_records,
        top_insights=top_insights,
        report=ReportSchema(
            report_json=run.report_json or {},
            report_summary=run.report_summary or "",
        ),
        total_tokens=run.total_tokens,
        error_flag=run.error_flag,
        degraded_reason=degraded_reason,
        correlation_id=run.correlation_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        observability=_observability_from_row(run),
    )


def _observability_from_row(run: Run) -> ObservabilitySchema | None:
    """Rebuild the observability trace/metrics summary from a run's stored JSON."""
    data = run.metrics
    if not data:
        return None
    return ObservabilitySchema(
        correlation_id=str(data.get("correlation_id", run.correlation_id)),
        total_duration_ms=float(data.get("total_duration_ms", 0.0)),
        node_count=int(data.get("node_count", 0)),
        success_count=int(data.get("success_count", 0)),
        failure_count=int(data.get("failure_count", 0)),
        success_rate=float(data.get("success_rate", 0.0)),
        total_api_calls=int(data.get("total_api_calls", 0)),
        total_retries=int(data.get("total_retries", 0)),
        total_tokens=int(data.get("total_tokens", 0)),
        nodes=[
            NodeMetricSchema(
                node=str(n.get("node", "")),
                duration_ms=float(n.get("duration_ms", 0.0)),
                success=bool(n.get("success", False)),
                retry_count=int(n.get("retry_count", 0)),
                api_calls=int(n.get("api_calls", 0)),
                error_code=n.get("error_code"),
            )
            for n in data.get("nodes", [])
        ],
    )


__all__ = [
    "enqueue_profile_run",
    "execute_run",
    "get_run_response",
    "run_profile_pipeline",
]
