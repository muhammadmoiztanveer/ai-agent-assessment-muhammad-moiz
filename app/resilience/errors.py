"""Error taxonomy and classification.

Real-world dependencies fail in two fundamentally different ways, and the system
must react differently to each:

- **Retryable** failures are transient — timeouts, connection resets, HTTP 429
  rate-limits, and HTTP 5xx server errors. Retrying (with backoff) is likely to
  succeed.
- **Non-retryable** failures are deterministic — malformed arguments, auth
  failures, HTTP 400/401/403/404/422. Retrying only wastes time and budget; the
  caller must handle or degrade instead.

:func:`classify` maps a raw exception or an :class:`httpx.Response` into a stable
:class:`ClassifiedError` with a machine-readable ``code``, a ``retryable`` flag,
and a redaction-safe ``detail`` payload. The retry executor and circuit breaker
both key their behaviour off this classification, so the "retryable vs not"
decision lives in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

# HTTP status codes that are safe to retry.
_RETRYABLE_STATUS: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})

# Explicit, human-friendly codes for the common non-retryable client statuses.
_NON_RETRYABLE_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    422: "unprocessable_entity",
}


@dataclass(frozen=True, slots=True)
class ClassifiedError:
    """A normalized, redaction-safe description of a failure.

    Attributes:
        code: Stable machine-readable identifier (e.g. ``"rate_limited"``).
        retryable: Whether retrying the operation may succeed.
        message: Short human-readable summary (never contains secrets).
        status_code: HTTP status code when the failure came from a response.
        retry_after_s: Server-advised wait (from a ``Retry-After`` header), if any.
        detail: Extra structured context for logs/metrics.
    """

    code: str
    retryable: bool
    message: str
    status_code: int | None = None
    retry_after_s: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """JSON-serializable form for persistence (``runs.error_detail``) and logs."""
        return {
            "code": self.code,
            "retryable": self.retryable,
            "message": self.message,
            "status_code": self.status_code,
            "retry_after_s": self.retry_after_s,
            "detail": self.detail,
        }


class ResilienceError(Exception):
    """Base exception carrying a :class:`ClassifiedError`.

    Raise subclasses so callers can branch on retryability via ``except`` while
    still having the full classification available on the instance.
    """

    def __init__(self, classified: ClassifiedError) -> None:
        super().__init__(classified.message)
        self.classified = classified

    @property
    def retryable(self) -> bool:
        return self.classified.retryable

    @property
    def code(self) -> str:
        return self.classified.code


class RetryableError(ResilienceError):
    """A transient failure that may succeed on retry."""


class NonRetryableError(ResilienceError):
    """A deterministic failure that must not be retried."""


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Parse a ``Retry-After`` header (delta-seconds or HTTP-date) into seconds."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    # Form 1: an integer number of seconds.
    try:
        return max(float(int(raw)), 0.0)
    except ValueError:
        pass
    # Form 2: an HTTP-date; convert to seconds from now.
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    delta = (when - datetime.now(UTC)).total_seconds()
    return max(delta, 0.0)


def _classify_status(response: httpx.Response) -> ClassifiedError:
    """Classify an HTTP response by its status code."""
    status = response.status_code
    detail: dict[str, Any] = {"method": response.request.method if response.request else None}

    if status in _RETRYABLE_STATUS:
        code = "rate_limited" if status == 429 else "server_error"
        return ClassifiedError(
            code=code,
            retryable=True,
            message=f"retryable HTTP {status}",
            status_code=status,
            retry_after_s=_parse_retry_after(response),
            detail=detail,
        )

    if status in _NON_RETRYABLE_STATUS_CODES:
        return ClassifiedError(
            code=_NON_RETRYABLE_STATUS_CODES[status],
            retryable=False,
            message=f"non-retryable HTTP {status}",
            status_code=status,
            detail=detail,
        )

    # Any other 4xx is a client error (don't retry); other 5xx already handled.
    if 400 <= status < 500:
        return ClassifiedError(
            code="client_error",
            retryable=False,
            message=f"client error HTTP {status}",
            status_code=status,
            detail=detail,
        )
    if status >= 500:
        return ClassifiedError(
            code="server_error",
            retryable=True,
            message=f"retryable HTTP {status}",
            status_code=status,
            retry_after_s=_parse_retry_after(response),
            detail=detail,
        )

    # 1xx/2xx/3xx are not failures; classify defensively as non-retryable.
    return ClassifiedError(
        code="unexpected_status",
        retryable=False,
        message=f"unexpected HTTP {status}",
        status_code=status,
        detail=detail,
    )


def classify(source: object) -> ClassifiedError:
    """Map an exception or ``httpx.Response`` into a :class:`ClassifiedError`.

    Recognized inputs:
      - an already-classified :class:`ResilienceError` (returned as-is),
      - an :class:`httpx.Response` or :class:`httpx.HTTPStatusError` (by status),
      - transport failures (timeouts, connection/network errors) → retryable,
      - :class:`ValueError` (e.g. bad arguments) → non-retryable ``invalid_input``,
      - anything else → non-retryable ``unknown``.
    """
    if isinstance(source, ResilienceError):
        return source.classified

    if isinstance(source, httpx.Response):
        return _classify_status(source)

    if isinstance(source, httpx.HTTPStatusError):
        return _classify_status(source.response)

    # Timeouts are the base of ConnectTimeout/ReadTimeout/etc. — check first.
    if isinstance(source, httpx.TimeoutException):
        return ClassifiedError(
            code="timeout",
            retryable=True,
            message="request timed out",
            detail={"exception": type(source).__name__},
        )

    if isinstance(source, httpx.ConnectError):
        return ClassifiedError(
            code="connection_error",
            retryable=True,
            message="failed to establish connection",
            detail={"exception": type(source).__name__},
        )

    # TransportError is the umbrella for lower-level network problems.
    if isinstance(source, httpx.TransportError):
        return ClassifiedError(
            code="network_error",
            retryable=True,
            message="network transport error",
            detail={"exception": type(source).__name__},
        )

    if isinstance(source, ValueError):
        return ClassifiedError(
            code="invalid_input",
            retryable=False,
            message="invalid input",
            detail={"exception": type(source).__name__},
        )

    if isinstance(source, Exception):
        return ClassifiedError(
            code="unknown",
            retryable=False,
            message="unclassified error",
            detail={"exception": type(source).__name__},
        )

    raise TypeError(f"classify() expects an Exception or httpx.Response, got {type(source)!r}")


def is_retryable(source: object) -> bool:
    """Convenience predicate: is this failure retryable?"""
    return classify(source).retryable


def to_resilience_error(source: Exception) -> ResilienceError:
    """Wrap an exception in the matching :class:`ResilienceError` subclass."""
    if isinstance(source, ResilienceError):
        return source
    classified = classify(source)
    if classified.retryable:
        return RetryableError(classified)
    return NonRetryableError(classified)
