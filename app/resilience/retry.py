"""Retry executor with exponential backoff and full jitter.

Wraps a callable so that transient (retryable) failures are re-attempted with an
exponentially increasing, jittered delay, while deterministic (non-retryable)
failures fail fast. This is real backoff logic — not a fixed ``sleep`` loop:

- **Exponential backoff:** ``base * 2**(attempt - 1)``, capped at ``max_delay``.
- **Full jitter:** the actual sleep is ``uniform(0, computed_delay)`` (AWS
  "full jitter" strategy) to avoid thundering-herd retry storms.
- **Retry-After aware:** if a 429/503 response advised a wait, it takes priority.
- **Classification-driven:** retryability comes from :func:`classify`, so only
  transient failures are retried.

``retry_call`` reports each retry through an optional callback (used by the graph
layer to record ``retry_count`` into metrics/logs) and injects ``sleep``/``rng``
for fully deterministic tests.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from app.config import Settings, get_settings
from app.resilience.errors import (
    ClassifiedError,
    RetryableError,
    classify,
    to_resilience_error,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Parameters controlling retry behaviour.

    Attributes:
        max_attempts: Total attempts including the first (``>= 1``).
        base_delay_s: Base backoff delay in seconds.
        max_delay_s: Upper bound on any single backoff delay (before jitter).
        jitter: Apply full jitter when ``True``; use the raw delay when ``False``.
    """

    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    jitter: bool = True

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> RetryPolicy:
        """Build a policy from application settings."""
        settings = settings or get_settings()
        return cls(
            max_attempts=settings.retry_max_attempts,
            base_delay_s=settings.retry_base_delay_s,
            max_delay_s=settings.retry_max_delay_s,
        )


@dataclass(frozen=True, slots=True)
class RetryAttempt:
    """Context passed to the ``on_retry`` callback before each backoff sleep."""

    attempt: int  # the attempt that just failed (1-based)
    delay_s: float  # how long we are about to sleep
    error: ClassifiedError


def compute_delay(
    attempt: int,
    policy: RetryPolicy,
    *,
    retry_after_s: float | None = None,
    rng: random.Random | None = None,
) -> float:
    """Compute the backoff delay before the next attempt.

    Args:
        attempt: The 1-based number of the attempt that just failed.
        policy: The retry policy.
        retry_after_s: Server-advised wait; when present it overrides backoff
            (still capped by ``max_delay_s``).
        rng: Random source (injectable for deterministic tests).

    Returns:
        Seconds to sleep before the next attempt.
    """
    exponential = policy.base_delay_s * (2 ** (attempt - 1))
    capped = min(exponential, policy.max_delay_s)

    if retry_after_s is not None:
        # Honour the server's advice, but never wait longer than our cap.
        return min(max(retry_after_s, 0.0), policy.max_delay_s)

    if not policy.jitter:
        return capped

    source = rng or random
    return source.uniform(0.0, capped)


def retry_call(
    func: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    on_retry: Callable[[RetryAttempt], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> T:
    """Execute ``func`` with retries on transient failures.

    Behaviour:
      - Returns ``func()``'s value on the first success.
      - On a **non-retryable** failure, re-raises immediately (as the matching
        :class:`ResilienceError` subclass).
      - On a **retryable** failure, sleeps ``compute_delay(...)`` and retries,
        up to ``policy.max_attempts`` total attempts.
      - After the final attempt fails, re-raises the last
        :class:`RetryableError` (retries exhausted).

    Args:
        func: Zero-argument callable performing the operation.
        policy: Retry policy (defaults to one built from settings).
        on_retry: Optional callback invoked with a :class:`RetryAttempt` right
            before each backoff sleep (for metrics/logging).
        sleep: Sleep function (injectable so tests don't actually wait).
        rng: Random source for jitter (injectable for determinism).

    Returns:
        The successful result of ``func``.
    """
    policy = policy or RetryPolicy.from_settings()

    last_error: RetryableError | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return func()
        except Exception as exc:
            classified = classify(exc)
            if not classified.retryable:
                # Deterministic failure: do not retry.
                raise to_resilience_error(exc) from exc

            last_error = RetryableError(classified)
            if attempt >= policy.max_attempts:
                break

            delay = compute_delay(
                attempt,
                policy,
                retry_after_s=classified.retry_after_s,
                rng=rng,
            )
            if on_retry is not None:
                on_retry(RetryAttempt(attempt=attempt, delay_s=delay, error=classified))
            sleep(delay)

    # Retries exhausted; surface the last transient error.
    assert last_error is not None
    raise last_error
