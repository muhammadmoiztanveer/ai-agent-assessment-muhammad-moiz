"""Circuit breaker for failing dependencies (bonus resilience feature).

When a dependency (e.g. DataForSEO) starts failing repeatedly, continuing to hit
it wastes time and budget and can make an outage worse. A circuit breaker trips
after a threshold of consecutive failures and then *fails fast* for a cooldown
window, giving the dependency time to recover.

State machine::

    CLOSED  ──(consecutive failures >= threshold)──▶  OPEN
      ▲                                                 │
      │                                     (cooldown elapsed)
      │                                                 ▼
      └────────(trial succeeds)──────────────────  HALF_OPEN
                                                        │
                                          (trial fails) ▼
                                                       OPEN

- **CLOSED:** calls flow normally; consecutive failures are counted, successes
  reset the count.
- **OPEN:** calls are rejected immediately with :class:`CircuitOpenError` until
  the cooldown elapses.
- **HALF_OPEN:** a single trial call is allowed; success closes the circuit,
  failure re-opens it for another cooldown.

The breaker is thread-safe (FastAPI serves requests on a threadpool) and takes an
injectable ``clock`` for deterministic tests.
"""

from __future__ import annotations

import enum
import threading
from collections.abc import Callable
from time import monotonic
from typing import TypeVar

from app.config import Settings, get_settings
from app.resilience.errors import ClassifiedError, NonRetryableError

T = TypeVar("T")


class CircuitState(enum.StrEnum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(NonRetryableError):
    """Raised when a call is rejected because the circuit is open.

    Classified as non-retryable: an immediate retry would just be rejected again.
    The pipeline should degrade (fallback) rather than spin.
    """

    def __init__(self, name: str, cooldown_remaining_s: float) -> None:
        super().__init__(
            ClassifiedError(
                code="circuit_open",
                retryable=False,
                message=f"circuit '{name}' is open; failing fast",
                detail={"cooldown_remaining_s": round(cooldown_remaining_s, 3)},
            )
        )
        self.name = name
        self.cooldown_remaining_s = cooldown_remaining_s


class CircuitBreaker:
    """A single-dependency circuit breaker.

    Args:
        name: Identifier used in errors, logs, and metrics.
        fail_threshold: Consecutive failures that trip the breaker (``>= 1``).
        cooldown_s: Seconds to stay open before allowing a half-open trial.
        clock: Monotonic time source in seconds (injectable for tests).
    """

    def __init__(
        self,
        name: str,
        *,
        fail_threshold: int = 5,
        cooldown_s: float = 30.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if fail_threshold < 1:
            raise ValueError("fail_threshold must be >= 1")
        self.name = name
        self.fail_threshold = fail_threshold
        self.cooldown_s = cooldown_s
        self._clock = clock

        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @classmethod
    def from_settings(cls, name: str, settings: Settings | None = None) -> CircuitBreaker:
        """Build a breaker from application settings."""
        settings = settings or get_settings()
        return cls(
            name,
            fail_threshold=settings.circuit_breaker_fail_threshold,
            cooldown_s=settings.circuit_breaker_cooldown_s,
        )

    # --- introspection ---------------------------------------------------- #
    @property
    def state(self) -> CircuitState:
        """Current state, accounting for an elapsed cooldown (OPEN → HALF_OPEN)."""
        with self._lock:
            self._maybe_half_open()
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._consecutive_failures

    def _cooldown_remaining(self) -> float:
        if self._opened_at is None:
            return 0.0
        elapsed = self._clock() - self._opened_at
        return max(self.cooldown_s - elapsed, 0.0)

    def _maybe_half_open(self) -> None:
        """Transition OPEN → HALF_OPEN once the cooldown window has elapsed."""
        if self._state is CircuitState.OPEN and self._cooldown_remaining() <= 0.0:
            self._state = CircuitState.HALF_OPEN

    # --- state transitions ------------------------------------------------ #
    def allow(self) -> bool:
        """Return whether a call may proceed right now.

        Rejects while OPEN (within cooldown). Permits a single trial in
        HALF_OPEN and normal traffic while CLOSED.
        """
        with self._lock:
            self._maybe_half_open()
            return self._state is not CircuitState.OPEN

    def record_success(self) -> None:
        """Record a successful call: reset failures and close the circuit."""
        with self._lock:
            self._consecutive_failures = 0
            self._state = CircuitState.CLOSED
            self._opened_at = None

    def record_failure(self) -> None:
        """Record a failed call: trip the breaker if the threshold is reached.

        A failure while HALF_OPEN immediately re-opens the circuit for a fresh
        cooldown window.
        """
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._trip()
                return
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.fail_threshold:
                self._trip()

    def _trip(self) -> None:
        """Open the circuit and start the cooldown (caller holds the lock)."""
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()
        if self._consecutive_failures < self.fail_threshold:
            self._consecutive_failures = self.fail_threshold

    # --- convenience wrapper --------------------------------------------- #
    def call(
        self,
        func: Callable[[], T],
        *,
        record_failure_on: Callable[[Exception], bool] | None = None,
    ) -> T:
        """Execute ``func`` under breaker protection.

        Raises :class:`CircuitOpenError` immediately if the breaker is open.
        Otherwise runs ``func``; a success closes/keeps-closed the circuit, and an
        exception is recorded as a failure (subject to ``record_failure_on``) and
        re-raised.

        Args:
            func: Zero-argument callable to execute.
            record_failure_on: Optional predicate deciding whether a given
                exception counts as a dependency failure. Defaults to counting
                every exception. Use this to avoid tripping the breaker on
                client-side errors (e.g. bad arguments) that don't indicate the
                dependency is unhealthy.
        """
        if not self.allow():
            raise CircuitOpenError(self.name, self._cooldown_remaining())

        try:
            result = func()
        except Exception as exc:
            if record_failure_on is None or record_failure_on(exc):
                self.record_failure()
            raise
        else:
            self.record_success()
            return result
