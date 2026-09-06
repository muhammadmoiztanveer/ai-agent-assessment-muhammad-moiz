"""Per-run, in-memory metrics collection.

A :class:`RunMetrics` instance accumulates observability data for a single
pipeline run: per-node latency and success/failure, total external API call
count, total retries, and token usage. At the end of a run :meth:`summary`
produces a compact dict that is logged and attached to the run response, and
:meth:`log_summary` emits it as a structured ``run.metrics`` event.

Scope is deliberately in-process and per-run (enough to debug a single run and
to satisfy the assessment). The README documents the production path
(OpenTelemetry / Prometheus) for cross-run aggregation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.observability.logging import get_logger

_logger = get_logger("metrics")


@dataclass(slots=True)
class NodeMetric:
    """Metrics captured for a single node execution."""

    node: str
    duration_ms: float
    success: bool
    retry_count: int = 0
    api_calls: int = 0
    error_code: str | None = None


@dataclass(slots=True)
class RunMetrics:
    """Accumulates metrics for one pipeline run."""

    correlation_id: str
    nodes: list[NodeMetric] = field(default_factory=list)
    total_tokens: int = 0
    _started_at: float = field(default_factory=time.perf_counter)
    _finished_at: float | None = None
    # Retries observed since the last node boundary, awaiting attribution to the
    # node during which they occurred (see ``take_pending_retries``).
    _pending_retries: int = 0

    # --- recording -------------------------------------------------------- #
    def record_node(
        self,
        *,
        node: str,
        duration_ms: float,
        success: bool,
        retry_count: int = 0,
        api_calls: int = 0,
        error_code: str | None = None,
    ) -> NodeMetric:
        """Record the outcome of a single node and return the stored metric."""
        metric = NodeMetric(
            node=node,
            duration_ms=duration_ms,
            success=success,
            retry_count=retry_count,
            api_calls=api_calls,
            error_code=error_code,
        )
        self.nodes.append(metric)
        return metric

    def add_tokens(self, tokens: int) -> None:
        """Accumulate LLM token usage for the run."""
        if tokens:
            self.total_tokens += tokens

    def record_retry(self) -> None:
        """Note that a transient failure was retried (attributed at node boundary)."""
        self._pending_retries += 1

    def take_pending_retries(self) -> int:
        """Return retries observed since the last call and reset the counter.

        Called once per node so retries are attributed to the node during which
        they happened (in practice, the retrieval node that makes API calls).
        """
        pending = self._pending_retries
        self._pending_retries = 0
        return pending

    def finish(self) -> None:
        """Mark the run as finished (freezes total duration)."""
        self._finished_at = time.perf_counter()

    # --- derived aggregates ---------------------------------------------- #
    @property
    def total_duration_ms(self) -> float:
        end = self._finished_at if self._finished_at is not None else time.perf_counter()
        return round((end - self._started_at) * 1000, 3)

    @property
    def total_api_calls(self) -> int:
        return sum(n.api_calls for n in self.nodes)

    @property
    def total_retries(self) -> int:
        return sum(n.retry_count for n in self.nodes)

    @property
    def success_count(self) -> int:
        return sum(1 for n in self.nodes if n.success)

    @property
    def failure_count(self) -> int:
        return sum(1 for n in self.nodes if not n.success)

    @property
    def success_rate(self) -> float:
        if not self.nodes:
            return 0.0
        return round(self.success_count / len(self.nodes), 4)

    # --- output ----------------------------------------------------------- #
    def summary(self) -> dict[str, Any]:
        """Build a JSON-serializable end-of-run summary."""
        return {
            "correlation_id": self.correlation_id,
            "total_duration_ms": self.total_duration_ms,
            "node_count": len(self.nodes),
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "total_api_calls": self.total_api_calls,
            "total_retries": self.total_retries,
            "total_tokens": self.total_tokens,
            "nodes": [
                {
                    "node": n.node,
                    "duration_ms": n.duration_ms,
                    "success": n.success,
                    "retry_count": n.retry_count,
                    "api_calls": n.api_calls,
                    "error_code": n.error_code,
                }
                for n in self.nodes
            ],
        }

    def log_summary(self) -> dict[str, Any]:
        """Emit the summary as a structured log event and return it."""
        summary = self.summary()
        _logger.info("run.metrics", **summary)
        return summary
