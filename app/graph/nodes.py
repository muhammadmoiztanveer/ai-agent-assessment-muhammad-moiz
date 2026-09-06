"""Graph nodes — thin instrumented wrappers around the five atomic agents.

Each node is a pure ``(PipelineState) -> state_delta`` function bound to a set of
:class:`~app.graph.dependencies.PipelineDependencies`. The agent does the real
work; the wrapper adds the cross-cutting concerns the spec's observability and
resilience sections require (§3.5, §3.6):

- **Timing + metrics.** Every node is timed and its outcome (duration, success,
  API-call count, error code) is recorded on the run's :class:`RunMetrics`.
- **Structured logging.** A ``node.finish`` event is emitted per node, already
  carrying the run's correlation id via the bound logging context.
- **Never crash the graph.** If a node body raises unexpectedly, the error is
  classified, logged, and turned into a degraded-state delta so the conditional
  edges route to the fallback path instead of the process blowing up.

The node bodies stay atomic: ``plan_queries`` only plans, ``retrieve_data`` only
fetches, and so on — matching the agent responsibilities exactly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.graph.dependencies import PipelineDependencies
from app.graph.state import (
    ANALYZE_DATA,
    BUILD_REPORT,
    FALLBACK,
    NORMALIZE_DATA,
    PLAN_QUERIES,
    RETRIEVE_DATA,
    PipelineState,
    RunStatus,
)
from app.observability.logging import get_logger
from app.observability.tracing import timed_span
from app.resilience.errors import classify

_logger = get_logger("graph.node")

NodeFn = Callable[[PipelineState], dict[str, Any]]


def _instrument(
    node_name: str,
    body: NodeFn,
    *,
    api_calls_of: Callable[[dict[str, Any]], int] | None = None,
) -> NodeFn:
    """Wrap a node body with timing, metrics, logging, and crash-safety."""

    def wrapped(state: PipelineState) -> dict[str, Any]:
        error_code: str | None = None
        with timed_span(node_name) as span:
            try:
                delta = body(state)
                success = True
            except Exception as exc:  # a node must never crash the whole graph
                classified = classify(exc)
                error_code = classified.code
                success = False
                _logger.error(
                    "graph.node.error",
                    node=node_name,
                    error_code=classified.code,
                    error=classified.message,
                )
                delta = {
                    "error_flag": True,
                    "degraded_reason": f"{node_name} failed: {classified.message}",
                }

        duration_ms = float(span["duration_ms"])
        api_calls = api_calls_of(delta) if (success and api_calls_of) else 0

        metrics = state.get("metrics")
        if metrics is not None:
            metrics.record_node(
                node=node_name,
                duration_ms=duration_ms,
                success=success,
                api_calls=api_calls,
                error_code=error_code,
            )
        _logger.info(
            "graph.node.finish",
            node=node_name,
            duration_ms=duration_ms,
            success=success,
        )
        return delta

    return wrapped


def _plan_body(deps: PipelineDependencies) -> NodeFn:
    def body(state: PipelineState) -> dict[str, Any]:
        plan = deps.planner.run(state["profile"], state.get("research_question", ""))
        return {"plan": plan, "planned_call_count": plan.call_count}

    return body


def _retrieve_body(deps: PipelineDependencies) -> NodeFn:
    def body(state: PipelineState) -> dict[str, Any]:
        outcome = deps.retrieval.run(state["plan"])
        delta: dict[str, Any] = {"retrieval": outcome}
        # Retrieval that partially fails but still yields usable data is a
        # degraded (partial) run, not a clean one — flag it while continuing.
        if outcome.errors:
            delta["error_flag"] = True
            delta["degraded_reason"] = f"{len(outcome.errors)} retrieval call(s) failed"
        return delta

    return body


def _normalize_body(deps: PipelineDependencies) -> NodeFn:
    def body(state: PipelineState) -> dict[str, Any]:
        outcome = state["retrieval"]
        records = deps.extraction.run(outcome.results, state["profile"])
        return {"normalized": records, "extracted_count": len(records)}

    return body


def _analyze_body(deps: PipelineDependencies) -> NodeFn:
    def body(state: PipelineState) -> dict[str, Any]:
        result = deps.analysis.run(state.get("normalized", []), state["profile"])
        return {"analysis": result}

    return body


def _report_body(deps: PipelineDependencies) -> NodeFn:
    def body(state: PipelineState) -> dict[str, Any]:
        analysis = state.get("analysis")
        insights = analysis.insights if analysis else ()
        recommendations = analysis.recommendations if analysis else ()
        narrative = analysis.narrative if analysis else ""
        degraded = bool(state.get("error_flag"))
        degraded_reason = state.get("degraded_reason")

        report = deps.report.run(
            profile=state["profile"],
            insights=insights,
            recommendations=recommendations,
            extracted_count=state.get("extracted_count", 0),
            analysis_narrative=narrative,
            degraded=degraded,
            degraded_reason=degraded_reason,
        )

        status = _final_status(degraded=degraded, has_output=bool(insights))
        return {
            "report": report,
            "status": status,
            "total_tokens": deps.total_tokens,
        }

    return body


def _fallback_body(deps: PipelineDependencies) -> NodeFn:
    """Deterministic degradation: record why the run degraded before reporting."""

    def body(state: PipelineState) -> dict[str, Any]:
        reason = _degraded_reason(state)
        _logger.warning("graph.fallback", reason=reason)
        return {"error_flag": True, "degraded_reason": reason}

    return body


def _final_status(*, degraded: bool, has_output: bool) -> RunStatus:
    """Map the run's shape to a terminal status (spec §4.2)."""
    if not degraded:
        return "completed"
    if has_output:
        return "partial"
    return "failed"


def _degraded_reason(state: PipelineState) -> str:
    """Explain, from the state, why the fallback path was taken."""
    plan = state.get("plan")
    if plan is None or not plan.is_valid:
        return "planner produced no executable retrieval calls"

    retrieval = state.get("retrieval")
    if retrieval is not None and not retrieval.has_usable_results:
        codes = sorted({e.code for e in retrieval.errors})
        detail = f" ({', '.join(codes)})" if codes else ""
        return f"all retrieval calls failed{detail}"

    if state.get("extracted_count", 0) == 0:
        return "no records could be normalized from the retrieved data"

    return state.get("degraded_reason") or "the pipeline degraded to a partial result"


def build_nodes(deps: PipelineDependencies) -> dict[str, NodeFn]:
    """Build the instrumented node functions bound to ``deps``."""
    return {
        PLAN_QUERIES: _instrument(PLAN_QUERIES, _plan_body(deps)),
        RETRIEVE_DATA: _instrument(
            RETRIEVE_DATA,
            _retrieve_body(deps),
            api_calls_of=lambda d: len(d["retrieval"].results) if "retrieval" in d else 0,
        ),
        NORMALIZE_DATA: _instrument(NORMALIZE_DATA, _normalize_body(deps)),
        ANALYZE_DATA: _instrument(ANALYZE_DATA, _analyze_body(deps)),
        BUILD_REPORT: _instrument(BUILD_REPORT, _report_body(deps)),
        FALLBACK: _instrument(FALLBACK, _fallback_body(deps)),
    }


__all__ = ["NodeFn", "build_nodes"]
