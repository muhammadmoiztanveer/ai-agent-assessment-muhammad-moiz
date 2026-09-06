"""API-level observability exposure + live failure-simulation endpoint.

Covers the enhancements that make the graded resilience/observability behaviour
visible through the API (and therefore the dashboard):

* every run response carries an ``observability`` block (the per-node trace +
  metrics the backend logs), and it is persisted so ``GET /runs/{uuid}`` returns it;
* ``POST /run?simulate=outage`` degrades to ``failed`` through the ``fallback``
  node without crashing, and ``?simulate=degraded`` yields a ``partial`` run.

A dedicated fast-retry client fixture keeps the simulated-failure runs quick by
collapsing backoff delays and the breaker cooldown (the retry maths itself is
unit-tested in ``test_failure_retry`` / ``test_resilience``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.config import get_settings
from app.db.database import init_engine


@pytest.fixture
def obs_client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """TestClient on a temp DB with near-zero retry delays for fast failure runs."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'obs.db'}")
    monkeypatch.setenv("RETRY_BASE_DELAY_S", "0.001")
    monkeypatch.setenv("RETRY_MAX_DELAY_S", "0.001")
    monkeypatch.setenv("CIRCUIT_BREAKER_COOLDOWN_S", "0.05")
    get_settings.cache_clear()
    settings = get_settings()
    init_engine(settings, create_tables=True)
    with TestClient(create_app(settings)) as client:
        yield client
    get_settings.cache_clear()


@pytest.fixture
def make_profile(obs_client: TestClient) -> Callable[[], str]:
    def _make() -> str:
        resp = obs_client.post(
            "/api/v1/profiles",
            json={"name": "Obs Co", "domain": "obsco.com", "industry": "SaaS"},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["profile_uuid"]

    return _make


_HAPPY_NODES = ["plan_queries", "retrieve_data", "normalize_data", "analyze_data", "build_report"]


def test_run_response_includes_observability_trace(
    obs_client: TestClient, make_profile: Callable[[], str]
) -> None:
    profile_uuid = make_profile()
    body = obs_client.post(f"/api/v1/profiles/{profile_uuid}/run").json()

    obs = body["observability"]
    assert obs is not None
    assert [n["node"] for n in obs["nodes"]] == _HAPPY_NODES
    assert obs["success_rate"] == 1.0
    assert obs["total_api_calls"] > 0
    assert obs["correlation_id"] == body["correlation_id"]
    # Retrieval is the node that makes the external API calls.
    retrieve = next(n for n in obs["nodes"] if n["node"] == "retrieve_data")
    assert retrieve["api_calls"] > 0


def test_observability_is_persisted_and_pollable(
    obs_client: TestClient, make_profile: Callable[[], str]
) -> None:
    profile_uuid = make_profile()
    run_uuid = obs_client.post(f"/api/v1/profiles/{profile_uuid}/run").json()["run_uuid"]

    fetched = obs_client.get(f"/api/v1/runs/{run_uuid}").json()
    assert fetched["observability"] is not None
    assert fetched["observability"]["node_count"] == len(_HAPPY_NODES)


def test_simulate_outage_degrades_to_failed_via_fallback(
    obs_client: TestClient, make_profile: Callable[[], str]
) -> None:
    profile_uuid = make_profile()
    resp = obs_client.post(f"/api/v1/profiles/{profile_uuid}/run?simulate=outage")

    assert resp.status_code == 200, resp.text  # degraded, not an HTTP error
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error_flag"] is True
    assert body["degraded_reason"]
    node_names = [n["node"] for n in body["observability"]["nodes"]]
    assert "fallback" in node_names
    # Extraction/Analysis are skipped on the fallback path.
    assert "analyze_data" not in node_names


def test_simulate_degraded_yields_partial(
    obs_client: TestClient, make_profile: Callable[[], str]
) -> None:
    profile_uuid = make_profile()
    body = obs_client.post(f"/api/v1/profiles/{profile_uuid}/run?simulate=degraded").json()

    assert body["status"] == "partial"
    assert body["error_flag"] is True
    assert body["extracted_records"] > 0  # some data survived the partial outage


def test_simulate_rejects_unknown_mode(
    obs_client: TestClient, make_profile: Callable[[], str]
) -> None:
    profile_uuid = make_profile()
    resp = obs_client.post(f"/api/v1/profiles/{profile_uuid}/run?simulate=nope")
    assert resp.status_code == 422
