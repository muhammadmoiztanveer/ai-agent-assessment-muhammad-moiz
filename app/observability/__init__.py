"""Observability layer: structured logging, correlation-id tracing, metrics."""

from __future__ import annotations

from app.observability.logging import (
    configure_logging,
    get_logger,
    log_node_event,
    redact_processor,
)
from app.observability.metrics import NodeMetric, RunMetrics
from app.observability.tracing import (
    correlation_context,
    get_correlation_id,
    new_correlation_id,
    set_correlation_id,
    timed_span,
)

__all__ = [
    "NodeMetric",
    "RunMetrics",
    "configure_logging",
    "correlation_context",
    "get_correlation_id",
    "get_logger",
    "log_node_event",
    "new_correlation_id",
    "redact_processor",
    "set_correlation_id",
    "timed_span",
]
