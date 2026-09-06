"""Correlation-ID tracing.

Every pipeline run is assigned a ``correlation_id`` (uuid4). It is stored in a
:class:`contextvars.ContextVar` so any code running within the run — nodes, tools,
the HTTP client — can read it without threading it through every function, and it
is bound into structlog's context so it appears on every log line automatically.

The correlation id is also persisted on the ``runs`` row and returned in API
responses, so a single request can be followed end-to-end: response → logs → DB.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import structlog

# Process-wide context variable holding the current run's correlation id.
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    """Generate a fresh, compact correlation id (uuid4 hex)."""
    return uuid.uuid4().hex


def get_correlation_id() -> str | None:
    """Return the correlation id bound to the current context, if any."""
    return _correlation_id.get()


def set_correlation_id(correlation_id: str) -> None:
    """Bind a correlation id to the current context and structlog's contextvars."""
    _correlation_id.set(correlation_id)
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


@contextmanager
def correlation_context(correlation_id: str | None = None) -> Iterator[str]:
    """Bind a correlation id for the duration of the ``with`` block.

    Args:
        correlation_id: Reuse an existing id (e.g. for a recheck tied to a prior
            run) or generate a new one when ``None``.

    Yields:
        The active correlation id.

    On exit the previous context state is restored so nested/sequential runs do
    not leak ids into one another.
    """
    correlation_id = correlation_id or new_correlation_id()
    token = _correlation_id.set(correlation_id)
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
    try:
        yield correlation_id
    finally:
        structlog.contextvars.unbind_contextvars("correlation_id")
        _correlation_id.reset(token)


@contextmanager
def timed_span(name: str) -> Iterator[dict[str, str | float]]:
    """Measure wall-clock duration of a block of work.

    Yields a mutable dict that is populated with ``duration_ms`` on exit, so
    callers can read the elapsed time after the block completes:

        with timed_span("plan") as span:
            ...
        span["duration_ms"]  # -> float
    """
    span: dict[str, str | float] = {"name": name}
    start = time.perf_counter()
    try:
        yield span
    finally:
        span["duration_ms"] = round((time.perf_counter() - start) * 1000, 3)
