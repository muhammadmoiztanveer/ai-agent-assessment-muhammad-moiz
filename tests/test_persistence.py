"""Phase 1 persistence tests: schema round-trip, relationships, filters, summary.

Uses a temporary file-based SQLite database (not in-memory) so data survives
across independent sessions, proving real persistence rather than session-local
identity-map caching.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.db.database import init_engine, session_scope
from app.db.models import (
    ContentType,
    Priority,
    RunStatus,
    VisibilityStatus,
)
from app.db.repositories import (
    QueryFilters,
    add_query,
    add_recommendation,
    create_profile,
    create_run,
    delete_recommendations_for_query,
    get_profile,
    latest_run_for_profile,
    profile_summary,
    queries_for_run,
    recommendations_for_profile_latest_run,
    update_query_metrics,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Initialize a fresh temp-file SQLite database for each test."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    init_engine(Settings(), create_tables=True)
    yield


def test_profile_run_query_recommendation_round_trip(db) -> None:
    # --- write everything in one transaction ---
    with session_scope() as session:
        profile = create_profile(
            session,
            name="Surfer SEO",
            domain="surferseo.com",
            industry="SEO software",
            description="Content optimization platform",
            competitors=["clearscope.io", "frase.io"],
        )
        run = create_run(
            session,
            profile_uuid=profile.profile_uuid,
            correlation_id="corr-123",
        )
        q1 = add_query(
            session,
            run_uuid=run.run_uuid,
            profile_uuid=profile.profile_uuid,
            query_text="best project management software",
            estimated_search_volume=8000,
            competitive_difficulty=40,
            opportunity_score=0.82,
            domain_visible=False,
            visibility_position=None,
            visibility_status=VisibilityStatus.NOT_VISIBLE,
        )
        add_query(
            session,
            run_uuid=run.run_uuid,
            profile_uuid=profile.profile_uuid,
            query_text="content optimization tool",
            estimated_search_volume=3000,
            competitive_difficulty=70,
            opportunity_score=0.35,
            domain_visible=True,
            visibility_position=3,
            visibility_status=VisibilityStatus.VISIBLE,
        )
        add_recommendation(
            session,
            run_uuid=run.run_uuid,
            target_query_uuid=q1.query_uuid,
            content_type=ContentType.BLOG_POST,
            title="The 2026 guide to project management software",
            rationale="High volume, brand not visible.",
            target_keywords=["project management", "pm software"],
            priority=Priority.HIGH,
        )
        profile_uuid = profile.profile_uuid
        run_uuid = run.run_uuid
        q1_uuid = q1.query_uuid

    # --- read back in a brand-new session (proves durability) ---
    with session_scope() as session:
        loaded = get_profile(session, profile_uuid)
        assert loaded is not None
        assert loaded.name == "Surfer SEO"
        assert loaded.competitors == ["clearscope.io", "frase.io"]
        assert loaded.created_at is not None

        # relationship traversal
        assert len(loaded.runs) == 1
        run = loaded.runs[0]
        assert run.run_uuid == run_uuid
        assert run.status == RunStatus.RUNNING
        assert run.correlation_id == "corr-123"

        # queries ordered by opportunity_score desc via relationship
        assert len(run.queries) == 2
        assert run.queries[0].query_text == "best project management software"
        assert run.queries[0].opportunity_score == pytest.approx(0.82)

        latest = latest_run_for_profile(session, profile_uuid)
        assert latest is not None and latest.run_uuid == run_uuid

        # recommendation FK links resolve
        recs = recommendations_for_profile_latest_run(session, profile_uuid)
        assert len(recs) == 1
        assert recs[0].target_query_uuid == q1_uuid
        assert recs[0].priority == Priority.HIGH
        assert recs[0].content_type == ContentType.BLOG_POST


def test_query_filters_and_pagination(db) -> None:
    with session_scope() as session:
        profile = create_profile(session, name="Acme", domain="acme.com")
        run = create_run(session, profile_uuid=profile.profile_uuid, correlation_id="c")
        # 5 queries with descending scores and mixed visibility
        specs = [
            (0.9, VisibilityStatus.NOT_VISIBLE),
            (0.7, VisibilityStatus.VISIBLE),
            (0.5, VisibilityStatus.UNKNOWN),
            (0.3, VisibilityStatus.NOT_VISIBLE),
            (0.1, VisibilityStatus.VISIBLE),
        ]
        for i, (score, status) in enumerate(specs):
            add_query(
                session,
                run_uuid=run.run_uuid,
                profile_uuid=profile.profile_uuid,
                query_text=f"q{i}",
                estimated_search_volume=1000,
                competitive_difficulty=50,
                opportunity_score=score,
                domain_visible=status == VisibilityStatus.VISIBLE,
                visibility_position=1 if status == VisibilityStatus.VISIBLE else None,
                visibility_status=status,
            )
        run_uuid = run.run_uuid

    with session_scope() as session:
        # sorted desc by default
        all_page = queries_for_run(session, run_uuid)
        assert all_page.total == 5
        scores = [q.opportunity_score for q in all_page.items]
        assert scores == sorted(scores, reverse=True)

        # min_score filter
        filtered = queries_for_run(session, run_uuid, QueryFilters(min_score=0.5))
        assert filtered.total == 3
        assert all(q.opportunity_score >= 0.5 for q in filtered.items)

        # status filter
        visible = queries_for_run(session, run_uuid, QueryFilters(status=VisibilityStatus.VISIBLE))
        assert visible.total == 2
        assert all(q.visibility_status == VisibilityStatus.VISIBLE for q in visible.items)

        # pagination
        p1 = queries_for_run(session, run_uuid, QueryFilters(page=1, per_page=2))
        p2 = queries_for_run(session, run_uuid, QueryFilters(page=2, per_page=2))
        assert len(p1.items) == 2
        assert len(p2.items) == 2
        assert p1.total == 5
        assert p1.total_pages == 3
        # no overlap between pages
        assert {q.query_uuid for q in p1.items}.isdisjoint({q.query_uuid for q in p2.items})


def test_profile_summary_stats(db) -> None:
    with session_scope() as session:
        profile = create_profile(session, name="Acme", domain="acme.com")
        profile_uuid = profile.profile_uuid

    # no runs yet
    with session_scope() as session:
        summary = profile_summary(session, profile_uuid)
        assert summary.total_runs == 0
        assert summary.latest_run_status is None
        assert summary.average_opportunity_score is None

    # one run with queries
    with session_scope() as session:
        run = create_run(session, profile_uuid=profile_uuid, correlation_id="c")
        run.status = RunStatus.COMPLETED
        for score in (0.6, 0.4):
            add_query(
                session,
                run_uuid=run.run_uuid,
                profile_uuid=profile_uuid,
                query_text="q",
                estimated_search_volume=100,
                competitive_difficulty=10,
                opportunity_score=score,
                domain_visible=False,
                visibility_position=None,
                visibility_status=VisibilityStatus.NOT_VISIBLE,
            )

    with session_scope() as session:
        summary = profile_summary(session, profile_uuid)
        assert summary.total_runs == 1
        assert summary.latest_run_status == RunStatus.COMPLETED
        assert summary.average_opportunity_score == pytest.approx(0.5)


def test_recheck_update_and_recommendation_replacement(db) -> None:
    with session_scope() as session:
        profile = create_profile(session, name="Acme", domain="acme.com")
        run = create_run(session, profile_uuid=profile.profile_uuid, correlation_id="c")
        q = add_query(
            session,
            run_uuid=run.run_uuid,
            profile_uuid=profile.profile_uuid,
            query_text="q",
            estimated_search_volume=100,
            competitive_difficulty=80,
            opportunity_score=0.2,
            domain_visible=False,
            visibility_position=None,
            visibility_status=VisibilityStatus.NOT_VISIBLE,
        )
        add_recommendation(
            session,
            run_uuid=run.run_uuid,
            target_query_uuid=q.query_uuid,
            content_type=ContentType.FAQ,
            title="old",
            rationale="old",
            priority=Priority.LOW,
        )
        q_uuid = q.query_uuid

    # simulate a recheck: query became visible, replace recommendations
    with session_scope() as session:
        q = latest_run_for_profile(session, profile.profile_uuid).queries[0]
        update_query_metrics(
            session,
            q,
            opportunity_score=0.05,
            domain_visible=True,
            visibility_position=2,
            visibility_status=VisibilityStatus.VISIBLE,
        )
        deleted = delete_recommendations_for_query(session, q_uuid)
        assert deleted == 1

    with session_scope() as session:
        q = latest_run_for_profile(session, profile.profile_uuid).queries[0]
        assert q.domain_visible is True
        assert q.visibility_position == 2
        assert q.visibility_status == VisibilityStatus.VISIBLE
        assert q.opportunity_score == pytest.approx(0.05)
        assert recommendations_for_profile_latest_run(session, profile.profile_uuid) == []
