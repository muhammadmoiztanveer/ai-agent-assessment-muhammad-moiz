"""Mandated test #1 — the happy path (spec §5).

Proves a full DAG run succeeds end-to-end, both at the graph level and through the
public HTTP API, and that every response field the assessment asks for is present
and correctly shaped. Everything is hermetic (mock DataForSEO + scripted LLM +
temp SQLite).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.graph.state import (
    ANALYZE_DATA,
    BUILD_REPORT,
    NORMALIZE_DATA,
    PLAN_QUERIES,
    RETRIEVE_DATA,
)
from tests.conftest import run_full_pipeline

# --------------------------------------------------------------------------- #
# Graph level
# --------------------------------------------------------------------------- #


def test_pipeline_completes_with_full_state() -> None:
    state = run_full_pipeline()

    assert state["status"] == "completed"
    assert state["error_flag"] is False
    assert state["planned_call_count"] >= 1
    assert state["extracted_count"] > 0

    analysis = state["analysis"]
    # Every normalized record becomes exactly one scored insight (atomicity).
    assert len(analysis.insights) == state["extracted_count"]
    assert analysis.recommendations  # at least one recommendation drafted

    report = state["report"]
    assert report.report_summary  # human-readable prose present
    assert report.report_json["summary"]["degraded"] is False
    assert report.report_json["top_insights"]


def test_pipeline_records_one_metric_per_node_in_order() -> None:
    state = run_full_pipeline(research_question="ai content optimization tools")

    executed = [n.node for n in state["metrics"].nodes]
    assert executed == [
        PLAN_QUERIES,
        RETRIEVE_DATA,
        NORMALIZE_DATA,
        ANALYZE_DATA,
        BUILD_REPORT,
    ]
    assert all(n.success for n in state["metrics"].nodes)


def test_top_insights_are_sorted_by_opportunity_score() -> None:
    state = run_full_pipeline()
    scores = [i.opportunity_score for i in state["analysis"].insights]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)


# --------------------------------------------------------------------------- #
# API level
# --------------------------------------------------------------------------- #


def test_run_endpoint_returns_completed_with_all_required_fields(
    api_client: TestClient,
    create_profile,
) -> None:
    puid = create_profile()
    resp = api_client.post(f"/api/v1/profiles/{puid}/run")
    assert resp.status_code == 200
    body = resp.json()

    # The exact response contract from spec §4.2.
    assert body["status"] == "completed"
    assert body["profile_uuid"] == puid
    assert body["run_uuid"]
    assert body["planned_retrieval_calls"] > 0
    assert body["extracted_records"] > 0
    assert body["error_flag"] is False
    assert body["correlation_id"]
    assert "total_tokens" in body

    scores = [i["opportunity_score"] for i in body["top_insights"]]
    assert scores == sorted(scores, reverse=True)

    assert set(body["report"]) == {"report_json", "report_summary"}
    assert body["report"]["report_summary"]
