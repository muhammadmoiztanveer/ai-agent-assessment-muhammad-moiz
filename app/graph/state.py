"""The shared, typed state that flows through the LangGraph DAG.

:class:`PipelineState` is the single object every node reads from and writes to.
Each node reads only what it needs and writes only its own outputs, which is what
keeps the five agents atomic (spec §3.2): the Planner writes ``plan``, Retrieval
writes ``retrieval``, Extraction writes ``normalized``, Analysis writes
``analysis``, and Report writes ``report`` — no node reaches across responsibilities.

LangGraph merges the partial ``dict`` a node returns into this state using a
last-value channel per key, so nodes stay pure ``(state) -> state_delta`` functions.
The typed value objects exchanged here are the framework-neutral dataclasses from
:mod:`app.agents.types`; keeping them out of any LangGraph type means the agents
remain testable and reusable without the graph.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from app.agents.types import (
    AnalysisResult,
    NormalizedQuery,
    ProfileContext,
    Report,
    RetrievalOutcome,
    RetrievalPlan,
)
from app.observability.metrics import RunMetrics

# The terminal status of a run, per spec §4.2.
RunStatus = Literal["running", "completed", "partial", "failed"]

# Node names — defined once so nodes, edges, and the builder never drift on a string.
PLAN_QUERIES = "plan_queries"
RETRIEVE_DATA = "retrieve_data"
NORMALIZE_DATA = "normalize_data"
ANALYZE_DATA = "analyze_data"
BUILD_REPORT = "build_report"
FALLBACK = "fallback"


class PipelineState(TypedDict, total=False):
    """Everything that flows through one pipeline run.

    ``total=False`` because each node contributes only its own slice; downstream
    nodes read what earlier nodes wrote. Control/observability fields
    (``status``, ``error_flag``, ``degraded_reason``, ``metrics``, ``total_tokens``)
    let the conditional edges route and let a run be traced and summarized.
    """

    # --- inputs / context ------------------------------------------------- #
    correlation_id: str
    profile: ProfileContext
    research_question: str

    # --- planner output --------------------------------------------------- #
    plan: RetrievalPlan
    planned_call_count: int

    # --- retrieval output ------------------------------------------------- #
    retrieval: RetrievalOutcome

    # --- extraction output ------------------------------------------------ #
    normalized: list[NormalizedQuery]
    extracted_count: int

    # --- analysis output -------------------------------------------------- #
    analysis: AnalysisResult

    # --- report output ---------------------------------------------------- #
    report: Report

    # --- control / resilience --------------------------------------------- #
    status: RunStatus
    error_flag: bool
    degraded_reason: str | None

    # --- observability ---------------------------------------------------- #
    metrics: RunMetrics
    total_tokens: int


def initial_state(
    *,
    profile: ProfileContext,
    research_question: str,
    correlation_id: str,
    metrics: RunMetrics,
) -> PipelineState:
    """Build the starting state for a run before the graph is invoked."""
    return PipelineState(
        correlation_id=correlation_id,
        profile=profile,
        research_question=research_question,
        planned_call_count=0,
        normalized=[],
        extracted_count=0,
        status="running",
        error_flag=False,
        degraded_reason=None,
        metrics=metrics,
        total_tokens=0,
    )


__all__ = [
    "ANALYZE_DATA",
    "BUILD_REPORT",
    "FALLBACK",
    "NORMALIZE_DATA",
    "PLAN_QUERIES",
    "RETRIEVE_DATA",
    "PipelineState",
    "RunStatus",
    "initial_state",
]
