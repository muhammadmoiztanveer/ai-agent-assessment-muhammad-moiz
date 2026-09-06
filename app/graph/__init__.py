"""Graph layer: the compiled LangGraph DAG that orchestrates the five agents.

Public surface:

- :func:`build_graph` / :func:`build_default_graph` — assemble and compile the DAG.
- :func:`run_pipeline` — execute one full run and return the final state.
- :class:`PipelineDependencies` / :func:`build_dependencies` — the agents + LLM
  a run executes against.
- :class:`PipelineState` and the node-name constants — the shared graph state.
"""

from __future__ import annotations

from app.graph.build import build_default_graph, build_graph, run_pipeline
from app.graph.dependencies import PipelineDependencies, build_dependencies
from app.graph.state import (
    ANALYZE_DATA,
    BUILD_REPORT,
    FALLBACK,
    NORMALIZE_DATA,
    PLAN_QUERIES,
    RETRIEVE_DATA,
    PipelineState,
    RunStatus,
    initial_state,
)

__all__ = [
    "ANALYZE_DATA",
    "BUILD_REPORT",
    "FALLBACK",
    "NORMALIZE_DATA",
    "PLAN_QUERIES",
    "RETRIEVE_DATA",
    "PipelineDependencies",
    "PipelineState",
    "RunStatus",
    "build_default_graph",
    "build_dependencies",
    "build_graph",
    "initial_state",
    "run_pipeline",
]
