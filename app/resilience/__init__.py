"""Resilience layer: error taxonomy, retry/backoff, circuit breaker."""

from __future__ import annotations

from app.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)
from app.resilience.errors import (
    ClassifiedError,
    NonRetryableError,
    ResilienceError,
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

__all__ = [
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    "ClassifiedError",
    "NonRetryableError",
    "ResilienceError",
    "RetryAttempt",
    "RetryPolicy",
    "RetryableError",
    "classify",
    "compute_delay",
    "is_retryable",
    "retry_call",
    "to_resilience_error",
]
