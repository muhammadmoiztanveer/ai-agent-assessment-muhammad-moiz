"""Conditional routing for the pipeline DAG.

These are the functions that make the graph non-linear (spec §3.1): after certain
nodes the next hop is chosen from the current state rather than being a fixed
edge. Each returns the *name* of the next node, and each guards the "unhappy"
branch to the deterministic ``fallback`` path so a bad plan, a dead dependency, or
empty data degrades gracefully instead of crashing (§3.5).

Routing map::

    plan_queries   → retrieve_data  if the plan has >= 1 executable call
                   → fallback       otherwise
    retrieve_data  → normalize_data if any retrieval call returned usable data
                   → fallback       if every retrieval call failed
    normalize_data → analyze_data   if >= 1 record was normalized
                   → fallback       if nothing could be normalized
"""

from __future__ import annotations

from app.graph.state import (
    ANALYZE_DATA,
    FALLBACK,
    NORMALIZE_DATA,
    RETRIEVE_DATA,
    PipelineState,
)


def route_after_plan(state: PipelineState) -> str:
    """Proceed to retrieval only when the planner produced an executable plan."""
    plan = state.get("plan")
    if plan is not None and plan.is_valid:
        return RETRIEVE_DATA
    return FALLBACK


def route_after_retrieve(state: PipelineState) -> str:
    """Proceed to normalization only when at least one call returned usable data."""
    outcome = state.get("retrieval")
    if outcome is not None and outcome.has_usable_results:
        return NORMALIZE_DATA
    return FALLBACK


def route_after_normalize(state: PipelineState) -> str:
    """Proceed to analysis only when at least one record was normalized."""
    if state.get("extracted_count", 0) > 0:
        return ANALYZE_DATA
    return FALLBACK


__all__ = [
    "route_after_normalize",
    "route_after_plan",
    "route_after_retrieve",
]
