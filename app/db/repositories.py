"""Repository layer — typed data-access functions.

All database reads/writes go through these functions so routes and services never
embed raw SQL or ORM query construction. Each function takes an explicit
:class:`~sqlalchemy.orm.Session` and returns ORM instances or plain values.

Transaction policy: mutating helpers ``flush`` (to populate defaults/PKs) but do
not ``commit`` — the caller controls the transaction boundary (via
``session_scope`` or a request-scoped session).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    ContentType,
    Priority,
    Profile,
    Query,
    Recommendation,
    Run,
    RunStatus,
    VisibilityStatus,
)


# --------------------------------------------------------------------------- #
# Filter / result value objects
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class QueryFilters:
    """Filtering + pagination parameters for listing queries."""

    min_score: float | None = None
    status: VisibilityStatus | None = None
    page: int = 1
    per_page: int = 20


@dataclass(frozen=True, slots=True)
class Page:
    """A paginated slice of query rows plus pagination metadata."""

    items: Sequence[Query]
    total: int
    page: int
    per_page: int

    @property
    def total_pages(self) -> int:
        if self.per_page <= 0:
            return 0
        return (self.total + self.per_page - 1) // self.per_page


@dataclass(frozen=True, slots=True)
class ProfileSummary:
    """Aggregated summary stats for a profile."""

    total_runs: int
    latest_run_status: RunStatus | None
    average_opportunity_score: float | None


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
def create_profile(
    session: Session,
    *,
    name: str,
    domain: str,
    industry: str | None = None,
    description: str | None = None,
    competitors: Iterable[str] | None = None,
) -> Profile:
    """Insert a new profile and return it (with generated PK and timestamp)."""
    profile = Profile(
        name=name,
        domain=domain,
        industry=industry,
        description=description,
        competitors=list(competitors or []),
    )
    session.add(profile)
    session.flush()
    return profile


def get_profile(session: Session, profile_uuid: str) -> Profile | None:
    """Fetch a profile by UUID, or ``None`` if it does not exist."""
    return session.get(Profile, profile_uuid)


def list_profiles(session: Session) -> Sequence[Profile]:
    """Return all profiles, newest first."""
    stmt = select(Profile).order_by(Profile.created_at.desc())
    return session.execute(stmt).scalars().all()


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #
def create_run(
    session: Session,
    *,
    profile_uuid: str,
    correlation_id: str,
    status: RunStatus = RunStatus.RUNNING,
) -> Run:
    """Create a run row (initially ``running``) for a profile."""
    run = Run(
        profile_uuid=profile_uuid,
        correlation_id=correlation_id,
        status=status,
    )
    session.add(run)
    session.flush()
    return run


def get_run(session: Session, run_uuid: str) -> Run | None:
    """Fetch a run by UUID, or ``None``."""
    return session.get(Run, run_uuid)


def runs_for_profile(session: Session, profile_uuid: str) -> Sequence[Run]:
    """All runs for a profile, most recent first."""
    stmt = select(Run).where(Run.profile_uuid == profile_uuid).order_by(Run.started_at.desc())
    return session.execute(stmt).scalars().all()


def latest_run_for_profile(session: Session, profile_uuid: str) -> Run | None:
    """The most recently started run for a profile, or ``None``."""
    stmt = (
        select(Run).where(Run.profile_uuid == profile_uuid).order_by(Run.started_at.desc()).limit(1)
    )
    return session.execute(stmt).scalars().first()


def count_runs_for_profile(session: Session, profile_uuid: str) -> int:
    """Total number of runs recorded for a profile."""
    stmt = select(func.count()).select_from(Run).where(Run.profile_uuid == profile_uuid)
    return int(session.execute(stmt).scalar_one())


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #
def add_query(
    session: Session,
    *,
    run_uuid: str,
    profile_uuid: str,
    query_text: str,
    estimated_search_volume: int,
    competitive_difficulty: int,
    opportunity_score: float,
    domain_visible: bool,
    visibility_position: int | None,
    visibility_status: VisibilityStatus,
) -> Query:
    """Insert a single discovered query for a run."""
    query = Query(
        run_uuid=run_uuid,
        profile_uuid=profile_uuid,
        query_text=query_text,
        estimated_search_volume=estimated_search_volume,
        competitive_difficulty=competitive_difficulty,
        opportunity_score=opportunity_score,
        domain_visible=domain_visible,
        visibility_position=visibility_position,
        visibility_status=visibility_status,
    )
    session.add(query)
    session.flush()
    return query


def get_query(session: Session, query_uuid: str) -> Query | None:
    """Fetch a query by UUID, or ``None``."""
    return session.get(Query, query_uuid)


def queries_for_run(
    session: Session,
    run_uuid: str,
    filters: QueryFilters | None = None,
) -> Page:
    """List queries for a run with optional filtering, sorting, and pagination.

    Results are sorted by ``opportunity_score`` descending (highest opportunity
    first), matching the API contract.
    """
    filters = filters or QueryFilters()

    conditions = [Query.run_uuid == run_uuid]
    if filters.min_score is not None:
        conditions.append(Query.opportunity_score >= filters.min_score)
    if filters.status is not None:
        conditions.append(Query.visibility_status == filters.status)

    count_stmt = select(func.count()).select_from(Query).where(*conditions)
    total = int(session.execute(count_stmt).scalar_one())

    page = max(filters.page, 1)
    per_page = max(filters.per_page, 1)
    offset = (page - 1) * per_page

    stmt = (
        select(Query)
        .where(*conditions)
        .order_by(Query.opportunity_score.desc(), Query.discovered_at.asc())
        .offset(offset)
        .limit(per_page)
    )
    items = session.execute(stmt).scalars().all()
    return Page(items=items, total=total, page=page, per_page=per_page)


def update_query_metrics(
    session: Session,
    query: Query,
    *,
    estimated_search_volume: int | None = None,
    competitive_difficulty: int | None = None,
    opportunity_score: float | None = None,
    domain_visible: bool | None = None,
    visibility_position: int | None = None,
    visibility_status: VisibilityStatus | None = None,
) -> Query:
    """Update mutable metrics on an existing query (used by recheck).

    Only non-``None`` arguments are applied. ``visibility_position`` is applied
    whenever ``visibility_status`` is provided so a query can be cleared to null.
    """
    if estimated_search_volume is not None:
        query.estimated_search_volume = estimated_search_volume
    if competitive_difficulty is not None:
        query.competitive_difficulty = competitive_difficulty
    if opportunity_score is not None:
        query.opportunity_score = opportunity_score
    if domain_visible is not None:
        query.domain_visible = domain_visible
    if visibility_status is not None:
        query.visibility_status = visibility_status
        query.visibility_position = visibility_position
    session.flush()
    return query


# --------------------------------------------------------------------------- #
# Recommendations
# --------------------------------------------------------------------------- #
def add_recommendation(
    session: Session,
    *,
    run_uuid: str,
    target_query_uuid: str,
    content_type: ContentType,
    title: str,
    rationale: str,
    target_keywords: Iterable[str] | None = None,
    priority: Priority = Priority.MEDIUM,
) -> Recommendation:
    """Insert a content recommendation targeting a query."""
    recommendation = Recommendation(
        run_uuid=run_uuid,
        target_query_uuid=target_query_uuid,
        content_type=content_type,
        title=title,
        rationale=rationale,
        target_keywords=list(target_keywords or []),
        priority=priority,
    )
    session.add(recommendation)
    session.flush()
    return recommendation


def recommendations_for_run(session: Session, run_uuid: str) -> Sequence[Recommendation]:
    """All recommendations produced by a run."""
    stmt = select(Recommendation).where(Recommendation.run_uuid == run_uuid)
    return session.execute(stmt).scalars().all()


def recommendations_for_profile_latest_run(
    session: Session, profile_uuid: str
) -> Sequence[Recommendation]:
    """Recommendations from the profile's most recent run (empty if no runs)."""
    latest = latest_run_for_profile(session, profile_uuid)
    if latest is None:
        return []
    return recommendations_for_run(session, latest.run_uuid)


def delete_recommendations_for_query(session: Session, query_uuid: str) -> int:
    """Remove all recommendations targeting a query; return the count deleted.

    Used by recheck before regenerating recommendations for the query.
    """
    recs = (
        session.execute(
            select(Recommendation).where(Recommendation.target_query_uuid == query_uuid)
        )
        .scalars()
        .all()
    )
    for rec in recs:
        session.delete(rec)
    session.flush()
    return len(recs)


# --------------------------------------------------------------------------- #
# Aggregates / summaries
# --------------------------------------------------------------------------- #
def profile_summary(session: Session, profile_uuid: str) -> ProfileSummary:
    """Compute summary stats for a profile.

    - ``total_runs``: number of runs for the profile.
    - ``latest_run_status``: status of the most recent run (``None`` if no runs).
    - ``average_opportunity_score``: mean opportunity score over the queries of
      the most recent run (``None`` if that run has no queries). Scoped to the
      latest run so it aligns with the ``/queries`` endpoint, which returns the
      latest run's queries.
    """
    total_runs = count_runs_for_profile(session, profile_uuid)
    latest = latest_run_for_profile(session, profile_uuid)

    if latest is None:
        return ProfileSummary(
            total_runs=total_runs,
            latest_run_status=None,
            average_opportunity_score=None,
        )

    avg_stmt = (
        select(func.avg(Query.opportunity_score))
        .select_from(Query)
        .where(Query.run_uuid == latest.run_uuid)
    )
    avg_value: Any = session.execute(avg_stmt).scalar_one_or_none()

    return ProfileSummary(
        total_runs=total_runs,
        latest_run_status=latest.status,
        average_opportunity_score=(round(float(avg_value), 4) if avg_value is not None else None),
    )
