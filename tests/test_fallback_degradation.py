"""Mandated test #3 — graceful degradation / fallback (spec §5, §3.5).

When a dependency fails, the pipeline must **not** crash. After retries are
exhausted the graph routes to the deterministic ``fallback`` node and still emits
a report, with ``error_flag`` set and a human-readable ``degraded_reason``:

- **Total retrieval failure** → status ``failed`` (nothing usable) but a report is
  still returned; the circuit breaker trips; analysis never runs.
- **Partial retrieval failure** → status ``partial`` (some usable data) and
  analysis still runs on what survived.

Failures are injected deterministically via the client's ``mock_hook`` seam, so no
real network flakiness is needed.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.graph.state import ANALYZE_DATA, FALLBACK
from app.integrations.dataforseo.client import DataForSeoClient
from app.resilience.circuit_breaker import CircuitBreaker, CircuitState
from tests.conftest import FAST_RETRY, make_settings, run_full_pipeline


def _always_failing_client(breaker: CircuitBreaker | None = None) -> DataForSeoClient:
    """Every DataForSEO call raises a transient error (simulated outage)."""

    def boom(_path: str, _payload: dict[str, Any]) -> None:
        raise httpx.ConnectTimeout("simulated total outage")

    return DataForSeoClient(
        settings=make_settings(),
        retry_policy=FAST_RETRY,
        mock_hook=boom,
        breaker=breaker,
    )


def _partial_failing_client() -> DataForSeoClient:
    """Only ``keyword_metrics`` fails; SERP / AI / LLM lookups still succeed."""

    def selective(_path: str, payload: dict[str, Any]) -> None:
        if "keywords" in payload:  # keyword_metrics payload shape
            raise httpx.ConnectTimeout("simulated metrics outage")

    return DataForSeoClient(settings=make_settings(), retry_policy=FAST_RETRY, mock_hook=selective)


# --------------------------------------------------------------------------- #
# Total failure → failed, but no crash
# --------------------------------------------------------------------------- #
def test_total_failure_degrades_to_failed_without_crashing() -> None:
    state = run_full_pipeline(_always_failing_client())

    assert state["status"] == "failed"
    assert state["error_flag"] is True
    assert state["extracted_count"] == 0
    assert state["degraded_reason"]  # a human-readable explanation is set

    # A report is still produced — the pipeline degraded, it did not blow up.
    assert state["report"].report_summary
    assert state["report"].report_json["summary"]["degraded"] is True

    executed = [n.node for n in state["metrics"].nodes]
    assert FALLBACK in executed
    assert ANALYZE_DATA not in executed


def test_total_failure_trips_the_circuit_breaker() -> None:
    # A low threshold makes the intent explicit; we hold our own reference so we
    # can inspect the breaker state after the run.
    breaker = CircuitBreaker("dataforseo", fail_threshold=2, cooldown_s=30.0)
    run_full_pipeline(_always_failing_client(breaker))
    # Repeated failures against a dead dependency should open the breaker.
    assert breaker.state in {CircuitState.OPEN, CircuitState.HALF_OPEN}


# --------------------------------------------------------------------------- #
# Partial failure → partial, analysis still runs
# --------------------------------------------------------------------------- #
def test_partial_failure_flags_partial_and_still_analyzes() -> None:
    state = run_full_pipeline(_partial_failing_client())

    assert state["status"] == "partial"
    assert state["error_flag"] is True
    assert state["extracted_count"] > 0  # SERP / AI / LLM data survived
    assert state["report"].report_json["summary"]["degraded"] is True

    executed = [n.node for n in state["metrics"].nodes]
    assert ANALYZE_DATA in executed  # analysis ran on the usable subset
