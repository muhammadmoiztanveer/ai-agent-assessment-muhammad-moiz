"""Phase 8 API contract tests.

Exercises every endpoint end-to-end through FastAPI's TestClient against a fresh
temp-file SQLite database in the default keyless/mock mode (hermetic, no network):
correct status codes (201/200/404/422), response shapes field-for-field, the
opportunity-score sort, filters + pagination, the uniform error envelope, and the
single-query recheck path.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.config import Settings
from app.db.database import init_engine


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient backed by a fresh temp-file SQLite database."""
    db_file = tmp_path / "api_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    settings = Settings()
    init_engine(settings, create_tables=True)
    return TestClient(create_app(settings))


def _create_profile(client: TestClient) -> str:
    resp = client.post(
        "/api/v1/profiles",
        json={
            "name": "Surfer SEO",
            "domain": "surferseo.com",
            "industry": "SEO software",
            "description": "Content optimization",
            "competitors": ["semrush.com", "ahrefs.com"],
        },
    )
    assert resp.status_code == 201
    return resp.json()["profile_uuid"]


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
def test_create_profile_returns_201_with_shape(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/profiles",
        json={"name": "Acme", "domain": "acme.com", "competitors": ["x.com"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "created"
    assert body["profile_uuid"]
    assert body["name"] == "Acme"
    assert body["domain"] == "acme.com"
    assert body["competitors"] == ["x.com"]
    assert "created_at" in body


def test_create_profile_missing_name_returns_422(client: TestClient) -> None:
    resp = client.post("/api/v1/profiles", json={"domain": "acme.com"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_create_profile_blank_name_returns_422(client: TestClient) -> None:
    resp = client.post("/api/v1/profiles", json={"name": "", "domain": "acme.com"})
    assert resp.status_code == 422


def test_get_unknown_profile_returns_404_envelope(client: TestClient) -> None:
    resp = client.get("/api/v1/profiles/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_get_profile_summary_before_and_after_run(client: TestClient) -> None:
    puid = _create_profile(client)

    pre = client.get(f"/api/v1/profiles/{puid}").json()
    assert pre["summary"] == {
        "total_runs": 0,
        "latest_run_status": None,
        "average_opportunity_score": None,
    }

    assert client.post(f"/api/v1/profiles/{puid}/run").status_code == 200

    post = client.get(f"/api/v1/profiles/{puid}").json()["summary"]
    assert post["total_runs"] == 1
    assert post["latest_run_status"] == "completed"
    assert post["average_opportunity_score"] is not None
    assert 0.0 <= post["average_opportunity_score"] <= 1.0


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
def test_run_pipeline_returns_completed_with_all_fields(client: TestClient) -> None:
    puid = _create_profile(client)
    resp = client.post(f"/api/v1/profiles/{puid}/run")
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] == "completed"
    assert body["profile_uuid"] == puid
    assert body["run_uuid"]
    assert body["planned_retrieval_calls"] > 0
    assert body["extracted_records"] > 0
    assert body["error_flag"] is False
    assert body["correlation_id"]
    assert "total_tokens" in body

    # top insights carry scores and are sorted by opportunity score (desc).
    scores = [i["opportunity_score"] for i in body["top_insights"]]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)

    # report has both machine and human parts.
    assert set(body["report"]) == {"report_json", "report_summary"}
    assert body["report"]["report_summary"]
    assert "top_insights" in body["report"]["report_json"]


def test_run_unknown_profile_returns_404(client: TestClient) -> None:
    resp = client.post("/api/v1/profiles/nope/run")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #
def test_queries_sorted_paginated_and_filtered(client: TestClient) -> None:
    puid = _create_profile(client)
    client.post(f"/api/v1/profiles/{puid}/run")

    resp = client.get(f"/api/v1/profiles/{puid}/queries")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"items", "page", "per_page", "total", "total_pages"}
    assert body["total"] >= 1

    scores = [q["opportunity_score"] for q in body["items"]]
    assert scores == sorted(scores, reverse=True)

    # Each query carries the full contract.
    q = body["items"][0]
    assert set(q) == {
        "query_uuid",
        "query_text",
        "estimated_search_volume",
        "competitive_difficulty",
        "opportunity_score",
        "domain_visible",
        "visibility_position",
        "visibility_status",
        "discovered_at",
    }

    # Pagination.
    paged = client.get(f"/api/v1/profiles/{puid}/queries?page=1&per_page=1").json()
    assert paged["per_page"] == 1
    assert len(paged["items"]) <= 1

    # min_score filter.
    filtered = client.get(f"/api/v1/profiles/{puid}/queries?min_score=0.6").json()
    assert all(q["opportunity_score"] >= 0.6 for q in filtered["items"])

    # status filter.
    nv = client.get(f"/api/v1/profiles/{puid}/queries?status=not_visible").json()
    assert all(q["visibility_status"] == "not_visible" for q in nv["items"])


def test_queries_for_profile_without_runs_is_empty(client: TestClient) -> None:
    puid = _create_profile(client)
    body = client.get(f"/api/v1/profiles/{puid}/queries").json()
    assert body["items"] == []
    assert body["total"] == 0


def test_queries_reject_bad_filters_with_422(client: TestClient) -> None:
    puid = _create_profile(client)
    assert client.get(f"/api/v1/profiles/{puid}/queries?min_score=9").status_code == 422
    assert client.get(f"/api/v1/profiles/{puid}/queries?status=bogus").status_code == 422
    assert client.get(f"/api/v1/profiles/{puid}/queries?per_page=0").status_code == 422


# --------------------------------------------------------------------------- #
# Recommendations
# --------------------------------------------------------------------------- #
def test_recommendations_shape(client: TestClient) -> None:
    puid = _create_profile(client)
    client.post(f"/api/v1/profiles/{puid}/run")

    resp = client.get(f"/api/v1/profiles/{puid}/recommendations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == len(body["items"])
    assert body["count"] >= 1

    rec = body["items"][0]
    assert set(rec) == {
        "recommendation_uuid",
        "target_query_uuid",
        "content_type",
        "title",
        "rationale",
        "target_keywords",
        "priority",
    }
    assert rec["content_type"] in {"blog_post", "landing_page", "faq"}
    assert rec["priority"] in {"high", "medium", "low"}


# --------------------------------------------------------------------------- #
# Recheck
# --------------------------------------------------------------------------- #
def test_recheck_updates_single_query(client: TestClient) -> None:
    puid = _create_profile(client)
    client.post(f"/api/v1/profiles/{puid}/run")
    queries = client.get(f"/api/v1/profiles/{puid}/queries").json()["items"]
    quid = queries[0]["query_uuid"]

    resp = client.post(f"/api/v1/queries/{quid}/recheck")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"completed", "partial"}
    assert body["query"]["query_uuid"] == quid
    assert body["correlation_id"]
    assert isinstance(body["recommendations"], list)


def test_recheck_unknown_query_returns_404(client: TestClient) -> None:
    resp = client.post("/api/v1/queries/nope/recheck")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #
def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
