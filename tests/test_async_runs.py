"""Async / background run execution — the spec §4.2 bonus.

Proves that ``POST /run?async=true`` enqueues a run (HTTP 202, ``status: queued``)
and returns immediately, that a background worker drives it to a terminal state,
and that ``GET /api/v1/runs/{run_uuid}`` polls the run's progress and final
result. Also covers the queue abstraction in isolation and the not-found paths.

Hermetic: uses the shared ``api_client`` fixture (temp SQLite, keyless mock
DataForSEO + scripted LLM). The background worker runs in-process, so polling
resolves in well under a second.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from fastapi.testclient import TestClient

from app.services.run_queue import ThreadPoolRunQueue

_TERMINAL = {"completed", "partial", "failed"}


def _poll_until_terminal(
    client: TestClient, run_uuid: str, *, timeout_s: float = 5.0
) -> dict[str, object]:
    """Poll GET /runs/{uuid} until the run reaches a terminal status."""
    deadline = time.monotonic() + timeout_s
    body: dict[str, object] = {}
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/runs/{run_uuid}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in _TERMINAL:
            return body
        time.sleep(0.02)
    raise AssertionError(f"run {run_uuid} did not finish within {timeout_s}s: {body}")


def test_async_run_returns_202_queued_immediately(
    api_client: TestClient, create_profile: Callable[..., str]
) -> None:
    profile_uuid = create_profile()
    resp = api_client.post(f"/api/v1/profiles/{profile_uuid}/run?async=true")

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["run_uuid"]
    assert body["profile_uuid"] == profile_uuid
    assert body["top_insights"] == []
    assert body["finished_at"] is None


def test_async_run_completes_in_background_and_is_pollable(
    api_client: TestClient, create_profile: Callable[..., str]
) -> None:
    profile_uuid = create_profile()
    run_uuid = api_client.post(f"/api/v1/profiles/{profile_uuid}/run?async=true").json()["run_uuid"]

    final = _poll_until_terminal(api_client, run_uuid)

    assert final["status"] == "completed"
    assert final["planned_retrieval_calls"] > 0
    assert final["extracted_records"] > 0
    assert len(final["top_insights"]) > 0  # type: ignore[arg-type]
    assert final["report"]["report_summary"]  # type: ignore[index]
    assert final["finished_at"] is not None
    assert final["correlation_id"]


def test_async_run_persists_queries_and_recommendations(
    api_client: TestClient, create_profile: Callable[..., str]
) -> None:
    profile_uuid = create_profile()
    run_uuid = api_client.post(f"/api/v1/profiles/{profile_uuid}/run?async=true").json()["run_uuid"]
    _poll_until_terminal(api_client, run_uuid)

    # The async run's data is visible through the normal profile endpoints.
    queries = api_client.get(f"/api/v1/profiles/{profile_uuid}/queries").json()
    assert queries["total"] > 0
    recs = api_client.get(f"/api/v1/profiles/{profile_uuid}/recommendations").json()
    assert len(recs["items"]) > 0

    summary = api_client.get(f"/api/v1/profiles/{profile_uuid}").json()["summary"]
    assert summary["total_runs"] == 1
    assert summary["latest_run_status"] == "completed"


def test_sync_run_still_returns_200_completed(
    api_client: TestClient, create_profile: Callable[..., str]
) -> None:
    """Default (synchronous) behaviour is unchanged by the async addition."""
    profile_uuid = create_profile()
    resp = api_client.post(f"/api/v1/profiles/{profile_uuid}/run")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["finished_at"] is not None


def test_get_unknown_run_returns_404(api_client: TestClient) -> None:
    resp = api_client.get("/api/v1/runs/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"]


def test_async_run_for_unknown_profile_returns_404(api_client: TestClient) -> None:
    resp = api_client.post("/api/v1/profiles/does-not-exist/run?async=true")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"]


def test_thread_pool_queue_executes_worker() -> None:
    """The queue backend invokes its worker for each submitted job."""
    seen: list[str] = []
    done = threading.Event()

    def worker(run_uuid: str) -> None:
        seen.append(run_uuid)
        done.set()

    queue = ThreadPoolRunQueue(worker, max_workers=1)
    try:
        queue.submit("run-123")
        assert done.wait(timeout=2.0)
    finally:
        queue.shutdown(wait=True)
    assert seen == ["run-123"]


def test_thread_pool_queue_swallows_worker_exceptions() -> None:
    """A crashing worker never escapes the pool thread (defensive guard)."""
    done = threading.Event()

    def boom(run_uuid: str) -> None:
        done.set()
        raise RuntimeError("worker blew up")

    queue = ThreadPoolRunQueue(boom, max_workers=1)
    try:
        queue.submit("run-xyz")
        assert done.wait(timeout=2.0)
        time.sleep(0.05)  # let the guard catch the exception
    finally:
        queue.shutdown(wait=True)
