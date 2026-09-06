"""Mandated test #2 — simulated API failure that retries and recovers (spec §5).

Covers the real resilience behaviour the assessment grades (§3.5):

- **Classification** — timeouts / 429 / 5xx are retryable; 400 / 401 / 404 are not.
- **Backoff + full jitter** — the computed delay grows exponentially, is capped,
  stays within ``[0, cap]`` when jittered, and honours a server ``Retry-After``.
- **Retry executor** — transient failures are re-attempted then succeed;
  non-retryable failures fail fast; exhausted retries surface a retryable error.
- **Integration** — an injected transient fault on a real tool call retries under
  the hood and the call ultimately succeeds.
"""

from __future__ import annotations

import random

import httpx
import pytest

from app.integrations.dataforseo.client import DataForSeoClient
from app.resilience.errors import (
    NonRetryableError,
    RetryableError,
    classify,
)
from app.resilience.retry import RetryAttempt, RetryPolicy, compute_delay, retry_call
from app.tools.dataforseo_tools import build_dataforseo_tools
from tests.conftest import FAST_RETRY, make_settings


# --------------------------------------------------------------------------- #
# Classification: retryable vs non-retryable
# --------------------------------------------------------------------------- #
def _response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://api.dataforseo.com/x")
    return httpx.Response(status, headers=headers or {}, request=request)


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_transient_statuses_are_retryable(status: int) -> None:
    assert classify(_response(status)).retryable is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_statuses_are_not_retryable(status: int) -> None:
    assert classify(_response(status)).retryable is False


def test_transport_errors_are_retryable() -> None:
    assert classify(httpx.ConnectTimeout("boom")).retryable is True
    assert classify(httpx.ReadTimeout("boom")).retryable is True
    assert classify(httpx.ConnectError("boom")).retryable is True


def test_retry_after_header_is_parsed() -> None:
    classified = classify(_response(429, {"Retry-After": "5"}))
    assert classified.retryable is True
    assert classified.retry_after_s == 5.0


# --------------------------------------------------------------------------- #
# Backoff + full jitter
# --------------------------------------------------------------------------- #
def test_backoff_grows_exponentially_without_jitter() -> None:
    policy = RetryPolicy(base_delay_s=0.5, max_delay_s=100.0, jitter=False)
    assert compute_delay(1, policy) == 0.5
    assert compute_delay(2, policy) == 1.0
    assert compute_delay(3, policy) == 2.0
    assert compute_delay(4, policy) == 4.0


def test_backoff_is_capped() -> None:
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=3.0, jitter=False)
    assert compute_delay(10, policy) == 3.0


def test_full_jitter_stays_within_bounds() -> None:
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=8.0, jitter=True)
    rng = random.Random(1234)
    for attempt in range(1, 6):
        cap = min(1.0 * 2 ** (attempt - 1), 8.0)
        for _ in range(50):
            delay = compute_delay(attempt, policy, rng=rng)
            assert 0.0 <= delay <= cap


def test_retry_after_overrides_backoff_but_respects_cap() -> None:
    policy = RetryPolicy(base_delay_s=0.5, max_delay_s=10.0, jitter=False)
    assert compute_delay(1, policy, retry_after_s=7.0) == 7.0
    # Never wait longer than the cap even if the server asks for more.
    assert compute_delay(1, policy, retry_after_s=999.0) == 10.0


# --------------------------------------------------------------------------- #
# Retry executor
# --------------------------------------------------------------------------- #
def test_retry_call_retries_transient_then_succeeds() -> None:
    attempts = {"n": 0}
    retries: list[RetryAttempt] = []

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ReadTimeout("transient")
        return "ok"

    result = retry_call(
        flaky,
        policy=RetryPolicy(max_attempts=5, base_delay_s=0.0, jitter=False),
        on_retry=retries.append,
        sleep=lambda _s: None,  # never actually wait
    )

    assert result == "ok"
    assert attempts["n"] == 3
    assert len(retries) == 2  # two retries preceded the success
    assert all(r.error.retryable for r in retries)


def test_retry_call_fast_fails_on_non_retryable() -> None:
    attempts = {"n": 0}

    def bad() -> None:
        attempts["n"] += 1
        raise httpx.HTTPStatusError("nope", request=None, response=_response(401))  # type: ignore[arg-type]

    with pytest.raises(NonRetryableError):
        retry_call(bad, policy=FAST_RETRY, sleep=lambda _s: None)
    assert attempts["n"] == 1  # never retried


def test_retry_call_raises_after_exhausting_retries() -> None:
    attempts = {"n": 0}

    def always_down() -> None:
        attempts["n"] += 1
        raise httpx.ConnectError("dependency down")

    with pytest.raises(RetryableError):
        retry_call(
            always_down,
            policy=RetryPolicy(max_attempts=3, base_delay_s=0.0, jitter=False),
            sleep=lambda _s: None,
        )
    assert attempts["n"] == 3  # all attempts used


# --------------------------------------------------------------------------- #
# Integration: a real tool call retries under the hood and recovers
# --------------------------------------------------------------------------- #
def test_tool_call_retries_transient_then_succeeds() -> None:
    state = {"n": 0}

    def hook(_path: str, _payload: dict) -> None:
        state["n"] += 1
        if state["n"] < 3:
            raise httpx.ReadTimeout("simulated transient outage")

    client = DataForSeoClient(settings=make_settings(), retry_policy=FAST_RETRY, mock_hook=hook)
    tool = build_dataforseo_tools(client)["serp_organic_search"]

    result = tool.invoke({"keyword": "flaky keyword"})

    assert result.ok is True
    assert client.last_retry_count == 2  # failed twice, third attempt succeeded
