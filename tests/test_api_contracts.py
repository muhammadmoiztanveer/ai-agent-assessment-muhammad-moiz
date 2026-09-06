"""Mandated coverage — REST API contracts (spec §4).

End-to-end contract tests through FastAPI's ``TestClient`` against a fresh temp
SQLite database (hermetic, keyless mock mode). They assert the status codes
(201 / 200 / 404 / 422), the exact response shapes, the opportunity-score sort,
filters + pagination, the uniform error envelope, and the single-query recheck
path — the full public surface of the six endpoints.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

# --------------------------------------------------------------------------- #
# POST /profiles
# --------------------------------------------------------------------------- #


def test_create_profile_returns_201_with_shape(api_client: TestClient) -> None:
    resp = api_client.post(
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


def test_create_profile_missing_name_returns_422(api_client: TestClient) -> None:
    resp = api_client.post("/api/v1/profiles", json={"domain": "acme.com"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_create_profile_blank_name_returns_422(api_client: TestClient) -> None:
    resp = api_client.post("/api/v1/profiles", json={"name": "", "domain": "acme.com"})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# GET /profiles/{uuid}
# --------------------------------------------------------------------------- #


def test_get_unknown_profile_returns_404_envelope(api_client: TestClient) -> None:
    resp = api_client.get("/api/v1/profiles/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_profile_summary_before_and_after_run(api_client: TestClient, create_profile) -> None:
    puid = create_profile()

    pre = api_client.get(f"/api/v1/profiles/{puid}").json()["summary"]
    assert pre == {"total_runs": 0, "latest_run_status": None, "average_opportunity_score": None}

    assert api_client.post(f"/api/v1/profiles/{puid}/run").status_code == 200

    post = api_client.get(f"/api/v1/profiles/{puid}").json()["summary"]
    assert post["total_runs"] == 1
    assert post["latest_run_status"] == "completed"
    assert 0.0 <= post["average_opportunity_score"] <= 1.0


# --------------------------------------------------------------------------- #
# POST /profiles/{uuid}/run
# --------------------------------------------------------------------------- #


def test_run_unknown_profile_returns_404(api_client: TestClient) -> None:
    resp = api_client.post("/api/v1/profiles/nope/run")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# --------------------------------------------------------------------------- #
# GET /profiles/{uuid}/queries
# --------------------------------------------------------------------------- #


def test_queries_contract_sort_filter_paginate(api_client: TestClient, create_profile) -> None:
    puid = create_profile()
    api_client.post(f"/api/v1/profiles/{puid}/run")

    body = api_client.get(f"/api/v1/profiles/{puid}/queries").json()
    assert set(body) == {"items", "page", "per_page", "total", "total_pages"}
    assert body["total"] >= 1

    scores = [q["opportunity_score"] for q in body["items"]]
    assert scores == sorted(scores, reverse=True)

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

    paged = api_client.get(f"/api/v1/profiles/{puid}/queries?page=1&per_page=1").json()
    assert paged["per_page"] == 1
    assert len(paged["items"]) <= 1

    filtered = api_client.get(f"/api/v1/profiles/{puid}/queries?min_score=0.6").json()
    assert all(q["opportunity_score"] >= 0.6 for q in filtered["items"])

    nv = api_client.get(f"/api/v1/profiles/{puid}/queries?status=not_visible").json()
    assert all(q["visibility_status"] == "not_visible" for q in nv["items"])


def test_queries_without_runs_is_empty(api_client: TestClient, create_profile) -> None:
    puid = create_profile()
    body = api_client.get(f"/api/v1/profiles/{puid}/queries").json()
    assert body["items"] == []
    assert body["total"] == 0


def test_queries_reject_bad_filters_with_422(api_client: TestClient, create_profile) -> None:
    puid = create_profile()
    assert api_client.get(f"/api/v1/profiles/{puid}/queries?min_score=9").status_code == 422
    assert api_client.get(f"/api/v1/profiles/{puid}/queries?status=bogus").status_code == 422
    assert api_client.get(f"/api/v1/profiles/{puid}/queries?per_page=0").status_code == 422


# --------------------------------------------------------------------------- #
# GET /profiles/{uuid}/recommendations
# --------------------------------------------------------------------------- #


def test_recommendations_contract(api_client: TestClient, create_profile) -> None:
    puid = create_profile()
    api_client.post(f"/api/v1/profiles/{puid}/run")

    body = api_client.get(f"/api/v1/profiles/{puid}/recommendations").json()
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
# POST /queries/{uuid}/recheck
# --------------------------------------------------------------------------- #


def test_recheck_updates_single_query(api_client: TestClient, create_profile) -> None:
    puid = create_profile()
    api_client.post(f"/api/v1/profiles/{puid}/run")
    quid = api_client.get(f"/api/v1/profiles/{puid}/queries").json()["items"][0]["query_uuid"]

    resp = api_client.post(f"/api/v1/queries/{quid}/recheck")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"completed", "partial"}
    assert body["query"]["query_uuid"] == quid
    assert body["correlation_id"]
    assert isinstance(body["recommendations"], list)


def test_recheck_unknown_query_returns_404(api_client: TestClient) -> None:
    resp = api_client.post("/api/v1/queries/nope/recheck")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
