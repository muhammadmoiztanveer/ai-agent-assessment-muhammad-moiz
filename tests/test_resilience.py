"""Phase 3 resilience tests: classification, retry/backoff, circuit breaker.

All tests are hermetic and fast — sleeps and clocks are injected so no test
actually waits, and jitter uses a seeded RNG for determinism.
"""

from __future__ import annotations

import random

import httpx
import pytest

from app.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)
from app.resilience.errors import (
    NonRetryableError,
    RetryableError,
    classify,
    is_retryable,
    to_resilience_error,
)
from app.resilience.retry import (
    RetryAttempt,
    RetryPolicy,
    compute_delay,
    retry_call,
)


def _response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    """Build an httpx.Response bound to a request (needed for classification)."""
    request = httpx.Request("GET", "https://api.dataforseo.com/v3/serp")
    return httpx.Response(status, headers=headers or {}, request=request)


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def test_transport_errors_are_retryable() -> None:
    assert classify(httpx.ConnectTimeout("t")).code == "timeout"
    assert classify(httpx.ReadTimeout("t")).retryable is True
    assert classify(httpx.ConnectError("c")).code == "connection_error"
    assert classify(httpx.ReadError("r")).code == "network_error"
    assert is_retryable(httpx.PoolTimeout("p")) is True


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_retryable_status_codes(status: int) -> None:
    err = classify(_response(status))
    assert err.retryable is True
    assert err.status_code == status


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "bad_request"),
        (401, "unauthorized"),
        (403, "forbidden"),
        (404, "not_found"),
        (422, "unprocessable_entity"),
    ],
)
def test_non_retryable_status_codes(status: int, code: str) -> None:
    err = classify(_response(status))
    assert err.retryable is False
    assert err.code == code


def test_generic_4xx_is_non_retryable_client_error() -> None:
    err = classify(_response(418))  # I'm a teapot
    assert err.code == "client_error"
    assert err.retryable is False


def test_http_status_error_is_classified_by_response() -> None:
    response = _response(503)
    exc = httpx.HTTPStatusError("boom", request=response.request, response=response)
    err = classify(exc)
    assert err.retryable is True
    assert err.status_code == 503


def test_retry_after_seconds_header_is_parsed() -> None:
    err = classify(_response(429, {"Retry-After": "7"}))
    assert err.retry_after_s == pytest.approx(7.0)


def test_retry_after_http_date_header_is_parsed() -> None:
    # A date far in the past should clamp to 0, not go negative.
    err = classify(_response(503, {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}))
    assert err.retry_after_s == pytest.approx(0.0)


def test_value_error_is_non_retryable() -> None:
    err = classify(ValueError("bad args"))
    assert err.code == "invalid_input"
    assert err.retryable is False


def test_unknown_exception_is_non_retryable() -> None:
    err = classify(RuntimeError("???"))
    assert err.code == "unknown"
    assert err.retryable is False


def test_resilience_error_passthrough() -> None:
    original = RetryableError(classify(_response(500)))
    assert classify(original) is original.classified


def test_to_resilience_error_maps_subclass() -> None:
    assert isinstance(to_resilience_error(httpx.ConnectError("x")), RetryableError)
    assert isinstance(to_resilience_error(ValueError("x")), NonRetryableError)


def test_classified_error_as_dict_is_serializable() -> None:
    d = classify(_response(429, {"Retry-After": "3"})).as_dict()
    assert d["code"] == "rate_limited"
    assert d["retryable"] is True
    assert d["retry_after_s"] == pytest.approx(3.0)


# --------------------------------------------------------------------------- #
# Backoff delay
# --------------------------------------------------------------------------- #
def test_compute_delay_exponential_without_jitter() -> None:
    policy = RetryPolicy(base_delay_s=0.5, max_delay_s=100.0, jitter=False)
    assert compute_delay(1, policy) == pytest.approx(0.5)
    assert compute_delay(2, policy) == pytest.approx(1.0)
    assert compute_delay(3, policy) == pytest.approx(2.0)
    assert compute_delay(4, policy) == pytest.approx(4.0)


def test_compute_delay_is_capped() -> None:
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=3.0, jitter=False)
    assert compute_delay(10, policy) == pytest.approx(3.0)


def test_compute_delay_full_jitter_is_bounded() -> None:
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=100.0, jitter=True)
    rng = random.Random(1234)
    for attempt in range(1, 6):
        ceiling = min(1.0 * 2 ** (attempt - 1), 100.0)
        for _ in range(50):
            delay = compute_delay(attempt, policy, rng=rng)
            assert 0.0 <= delay <= ceiling


def test_compute_delay_respects_retry_after() -> None:
    policy = RetryPolicy(base_delay_s=0.5, max_delay_s=100.0, jitter=False)
    assert compute_delay(1, policy, retry_after_s=12.0) == pytest.approx(12.0)


def test_compute_delay_retry_after_still_capped() -> None:
    policy = RetryPolicy(base_delay_s=0.5, max_delay_s=5.0, jitter=False)
    assert compute_delay(1, policy, retry_after_s=999.0) == pytest.approx(5.0)


# --------------------------------------------------------------------------- #
# retry_call
# --------------------------------------------------------------------------- #
def test_retry_call_returns_on_first_success() -> None:
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        return "ok"

    assert retry_call(fn, policy=RetryPolicy(max_attempts=3), sleep=lambda _: None) == "ok"
    assert calls["n"] == 1


def test_retry_call_retries_transient_then_succeeds() -> None:
    attempts = {"n": 0}
    retries: list[RetryAttempt] = []

    def fn() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("transient")
        return "recovered"

    result = retry_call(
        fn,
        policy=RetryPolicy(max_attempts=5, jitter=False),
        on_retry=retries.append,
        sleep=lambda _: None,
    )
    assert result == "recovered"
    assert attempts["n"] == 3
    assert len(retries) == 2  # two retries before the third succeeds
    assert all(r.error.retryable for r in retries)


def test_retry_call_does_not_retry_non_retryable() -> None:
    attempts = {"n": 0}

    def fn() -> None:
        attempts["n"] += 1
        raise ValueError("bad args")

    with pytest.raises(NonRetryableError):
        retry_call(fn, policy=RetryPolicy(max_attempts=5), sleep=lambda _: None)
    assert attempts["n"] == 1  # tried exactly once


def test_retry_call_exhausts_and_raises_retryable() -> None:
    attempts = {"n": 0}
    slept: list[float] = []

    def fn() -> None:
        attempts["n"] += 1
        raise httpx.ReadTimeout("still down")

    with pytest.raises(RetryableError):
        retry_call(
            fn,
            policy=RetryPolicy(max_attempts=3, jitter=False),
            sleep=slept.append,
        )
    assert attempts["n"] == 3  # all attempts used
    assert len(slept) == 2  # slept between attempts, not after the last


def test_retry_call_uses_retry_after_from_response_error() -> None:
    slept: list[float] = []
    attempts = {"n": 0}

    def fn() -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.HTTPStatusError(
                "rate limited",
                request=_response(429).request,
                response=_response(429, {"Retry-After": "4"}),
            )
        return "ok"

    result = retry_call(
        fn,
        policy=RetryPolicy(max_attempts=3, max_delay_s=100.0, jitter=False),
        sleep=slept.append,
    )
    assert result == "ok"
    assert slept == [pytest.approx(4.0)]


# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #
class FakeClock:
    """A controllable monotonic clock for deterministic breaker tests."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_breaker_opens_after_threshold() -> None:
    cb = CircuitBreaker("dfs", fail_threshold=3, cooldown_s=30.0, clock=FakeClock())
    assert cb.state is CircuitState.CLOSED
    for _ in range(3):
        cb.record_failure()
    assert cb.state is CircuitState.OPEN
    assert cb.allow() is False


def test_breaker_success_resets_failures() -> None:
    cb = CircuitBreaker("dfs", fail_threshold=3, clock=FakeClock())
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.failure_count == 0
    cb.record_failure()
    assert cb.state is CircuitState.CLOSED  # count restarted, not tripped


def test_breaker_half_open_after_cooldown_then_closes_on_success() -> None:
    clock = FakeClock()
    cb = CircuitBreaker("dfs", fail_threshold=2, cooldown_s=30.0, clock=clock)
    cb.record_failure()
    cb.record_failure()
    assert cb.state is CircuitState.OPEN

    clock.advance(31.0)
    assert cb.state is CircuitState.HALF_OPEN
    assert cb.allow() is True

    cb.record_success()
    assert cb.state is CircuitState.CLOSED
    assert cb.failure_count == 0


def test_breaker_half_open_failure_reopens() -> None:
    clock = FakeClock()
    cb = CircuitBreaker("dfs", fail_threshold=2, cooldown_s=30.0, clock=clock)
    cb.record_failure()
    cb.record_failure()
    clock.advance(31.0)
    assert cb.state is CircuitState.HALF_OPEN

    cb.record_failure()  # trial fails
    assert cb.state is CircuitState.OPEN
    # cooldown window restarts from the new open time
    clock.advance(31.0)
    assert cb.state is CircuitState.HALF_OPEN


def test_breaker_call_rejects_when_open() -> None:
    cb = CircuitBreaker("dfs", fail_threshold=1, cooldown_s=30.0, clock=FakeClock())
    cb.record_failure()  # trips immediately

    def fn() -> str:
        return "should not run"

    with pytest.raises(CircuitOpenError) as exc_info:
        cb.call(fn)
    assert exc_info.value.retryable is False
    assert exc_info.value.name == "dfs"


def test_breaker_call_records_success_and_failure() -> None:
    cb = CircuitBreaker("dfs", fail_threshold=2, clock=FakeClock())

    assert cb.call(lambda: 42) == 42
    assert cb.failure_count == 0

    def boom() -> None:
        raise httpx.ConnectError("down")

    with pytest.raises(httpx.ConnectError):
        cb.call(boom)
    assert cb.failure_count == 1


def test_breaker_call_respects_failure_predicate() -> None:
    cb = CircuitBreaker("dfs", fail_threshold=2, clock=FakeClock())

    def bad_args() -> None:
        raise ValueError("client mistake")

    # Client errors should not trip the breaker.
    with pytest.raises(ValueError):
        cb.call(bad_args, record_failure_on=is_retryable)
    assert cb.failure_count == 0
    assert cb.state is CircuitState.CLOSED


def test_breaker_from_settings_builds() -> None:
    cb = CircuitBreaker.from_settings("dfs")
    assert cb.fail_threshold >= 1
    assert cb.state is CircuitState.CLOSED
