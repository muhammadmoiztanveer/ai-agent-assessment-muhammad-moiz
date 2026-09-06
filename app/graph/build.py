"""Build and compile the LangGraph DAG (spec §3.1 / R1, R2, R14).

:func:`build_graph` assembles the five agent nodes plus the deterministic
``fallback`` node into an explicit :class:`~langgraph.graph.StateGraph` with named
nodes and conditional edges, then compiles it into a runnable graph. The topology
is::

    START ─▶ plan_queries
                 │ route_after_plan
                 ├─(valid plan)────▶ retrieve_data
                 └─(no calls)──────▶ fallback
    retrieve_data
                 │ route_after_retrieve
                 ├─(usable data)───▶ normalize_data
                 └─(all failed)────▶ fallback
    normalize_data
                 │ route_after_normalize
                 ├─(extracted > 0)─▶ analyze_data
                 └─(nothing)───────▶ fallback
    analyze_data ─────────────────▶ build_report
    fallback ─────────────────────▶ build_report
    build_report ─────────────────▶ END

Every terminal path runs ``build_report`` so the pipeline always returns a report
— ``completed`` on the happy path, or ``partial``/``failed`` with an error flag
when it degrades.

:func:`run_pipeline` is a thin convenience that binds a correlation id and a
per-run metrics collector, invokes the compiled graph, and returns the final
:class:`~app.graph.state.PipelineState`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from langgraph.graph import END, START, StateGraph

from app.agents.types import ProfileContext
from app.config import Settings, get_settings
from app.graph.dependencies import PipelineDependencies, build_dependencies
from app.graph.edges import (
    route_after_normalize,
    route_after_plan,
    route_after_retrieve,
)
from app.graph.nodes import build_nodes
from app.graph.state import (
    ANALYZE_DATA,
    BUILD_REPORT,
    FALLBACK,
    NORMALIZE_DATA,
    PLAN_QUERIES,
    RETRIEVE_DATA,
    PipelineState,
    initial_state,
)
from app.integrations.dataforseo.client import MockHook, build_client
from app.observability.logging import get_logger
from app.observability.metrics import RunMetrics
from app.observability.tracing import correlation_context, new_correlation_id

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

_logger = get_logger("graph")


def build_graph(deps: PipelineDependencies) -> CompiledStateGraph:
    """Assemble and compile the pipeline DAG bound to ``deps``."""
    nodes = build_nodes(deps)
    builder: StateGraph = StateGraph(PipelineState)

    # Register every node under its stable name. (LangGraph's add_node overloads
    # don't narrow cleanly to our ``(PipelineState) -> dict`` node functions, so
    # the arg-type is silenced here; the runtime contract is exact.)
    for name, fn in nodes.items():
        builder.add_node(name, fn)  # type: ignore[call-overload]

    # Entry.
    builder.add_edge(START, PLAN_QUERIES)

    # Conditional routing (the non-linear part of the graph).
    builder.add_conditional_edges(
        PLAN_QUERIES,
        route_after_plan,
        {RETRIEVE_DATA: RETRIEVE_DATA, FALLBACK: FALLBACK},
    )
    builder.add_conditional_edges(
        RETRIEVE_DATA,
        route_after_retrieve,
        {NORMALIZE_DATA: NORMALIZE_DATA, FALLBACK: FALLBACK},
    )
    builder.add_conditional_edges(
        NORMALIZE_DATA,
        route_after_normalize,
        {ANALYZE_DATA: ANALYZE_DATA, FALLBACK: FALLBACK},
    )

    # Both the happy path and the fallback path converge on the report.
    builder.add_edge(ANALYZE_DATA, BUILD_REPORT)
    builder.add_edge(FALLBACK, BUILD_REPORT)
    builder.add_edge(BUILD_REPORT, END)

    return builder.compile()


def build_default_graph(settings: Settings | None = None) -> CompiledStateGraph:
    """Build the graph with a fresh, default set of dependencies."""
    return build_graph(build_dependencies(settings))


def run_pipeline(
    *,
    profile: ProfileContext,
    research_question: str,
    settings: Settings | None = None,
    correlation_id: str | None = None,
    deps: PipelineDependencies | None = None,
    mock_hook: MockHook | None = None,
) -> PipelineState:
    """Execute one full pipeline run and return the final state.

    A per-run :class:`RunMetrics` collector is created and its token callback is
    wired into the LLM client (via ``deps``), so the returned state carries an
    accurate ``total_tokens`` and the metrics summary is logged at the end.

    ``mock_hook`` (mock mode only) injects deterministic transient faults through
    the real retry/circuit-breaker path — used by the ``?simulate=`` demo and the
    resilience tests to exercise graceful degradation end-to-end.
    """
    settings = settings or get_settings()
    correlation_id = correlation_id or new_correlation_id()
    metrics = RunMetrics(correlation_id=correlation_id)

    # Build dependencies bound to this run's metrics so token usage is captured.
    if deps is None:
        client = None
        if mock_hook is not None:
            # Build the client here so its retries are still counted into metrics.
            client = build_client(
                settings, mock_hook=mock_hook, on_retry=lambda _a: metrics.record_retry()
            )
        deps = build_dependencies(settings, metrics=metrics, client=client)
    graph = build_graph(deps)

    with correlation_context(correlation_id):
        _logger.info(
            "graph.run.start",
            profile=profile.name,
            domain=profile.domain,
            research_question=research_question,
        )
        start = initial_state(
            profile=profile,
            research_question=research_question,
            correlation_id=correlation_id,
            metrics=metrics,
        )
        final_state = cast(PipelineState, graph.invoke(start))
        metrics.finish()
        metrics.log_summary()
        _logger.info(
            "graph.run.finish",
            status=final_state.get("status"),
            error_flag=final_state.get("error_flag", False),
            total_tokens=final_state.get("total_tokens", 0),
        )

    return final_state


__all__ = [
    "build_default_graph",
    "build_graph",
    "run_pipeline",
]
