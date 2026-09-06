"""Phase 7 tests: the LangGraph DAG.

These are end-to-end integration tests over the compiled graph (still hermetic:
no network, no API key). They prove the three things the spec cares about for
orchestration (§3.1, §3.5):

1. **Happy path** — a full run reaches ``build_report`` via
   plan → retrieve → normalize → analyze, ending ``completed`` with every
   response field populated and one metric per executed node.
2. **Graceful degradation** — when every retrieval call fails, the graph routes
   to the ``fallback`` node and still returns a report with ``error_flag`` set,
   without crashing.
3. **Partial run** — when some retrieval calls fail but usable data remains, the
   run completes through analysis yet is flagged ``partial``.

Plus unit tests for the conditional routers and the compiled graph's shape.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.agents.types import ProfileContext, RetrievalOutcome, RetrievalPlan
from app.config import Settings
from app.graph import (
    ANALYZE_DATA,
    BUILD_REPORT,
    FALLBACK,
    NORMALIZE_DATA,
    PLAN_QUERIES,
    RETRIEVE_DATA,
    build_dependencies,
    build_graph,
    run_pipeline,
)
from app.graph.edges import (
    route_after_normalize,
    route_after_plan,
    route_after_retrieve,
)
from app.integrations.dataforseo.client import DataForSeoClient
from app.llm.mock import ScriptedLLMClient
from app.resilience.retry import RetryPolicy

# A no-sleep retry policy so exhausting retries in the failure test is instant.
_FAST = RetryPolicy(max_attempts=2, base_delay_s=0.0, max_delay_s=0.0, jitter=False)


def _settings() -> Settings:
    return Settings(
        OPP_WEIGHT_VOLUME=0.4,
        OPP_WEIGHT_DIFFICULTY=0.3,
        OPP_WEIGHT_GAP=0.3,
        OPP_VOLUME_CAP=10_000,
    )


def _profile() -> ProfileContext:
    return ProfileContext(
        name="Surfer SEO",
        domain="https://www.surferseo.com",
        industry="SEO",
        competitors=("ahrefs.com", "semrush.com"),
    )


def _deps(client: DataForSeoClient):  # type: ignore[no-untyped-def]
    """Dependencies bound to an injected client and a deterministic keyless LLM."""
    return build_dependencies(
        _settings(),
        client=client,
        llm=ScriptedLLMClient(),
    )


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
def test_happy_path_completes_with_full_response() -> None:
    deps = _deps(DataForSeoClient(settings=_settings(), retry_policy=_FAST))
    state = run_pipeline(
        profile=_profile(),
        research_question="best project management software",
        settings=_settings(),
        deps=deps,
    )

    assert state["status"] == "completed"
    assert state["error_flag"] is False
    assert state["planned_call_count"] >= 1
    assert state["extracted_count"] > 0

    analysis = state["analysis"]
    assert len(analysis.insights) == state["extracted_count"]
    assert analysis.recommendations  # at least one recommendation drafted

    report = state["report"]
    assert report.report_summary
    assert report.report_json["summary"]["degraded"] is False
    assert report.report_json["top_insights"]


def test_happy_path_records_one_metric_per_executed_node() -> None:
    deps = _deps(DataForSeoClient(settings=_settings(), retry_policy=_FAST))
    state = run_pipeline(
        profile=_profile(),
        research_question="ai content optimization",
        settings=_settings(),
        deps=deps,
    )

    nodes = [n.node for n in state["metrics"].nodes]
    assert nodes == [PLAN_QUERIES, RETRIEVE_DATA, NORMALIZE_DATA, ANALYZE_DATA, BUILD_REPORT]
    # The retrieval node reports the number of executed API calls.
    retrieve_metric = next(n for n in state["metrics"].nodes if n.node == RETRIEVE_DATA)
    assert retrieve_metric.api_calls == state["planned_call_count"]
    assert all(n.success for n in state["metrics"].nodes)


# --------------------------------------------------------------------------- #
# Graceful degradation — total retrieval failure routes to fallback
# --------------------------------------------------------------------------- #
def _always_failing_client() -> DataForSeoClient:
    def boom(_path: str, _payload: dict[str, Any]) -> None:
        raise httpx.ConnectTimeout("simulated connection timeout")

    return DataForSeoClient(settings=_settings(), retry_policy=_FAST, mock_hook=boom)


def test_total_retrieval_failure_degrades_without_crashing() -> None:
    deps = _deps(_always_failing_client())
    state = run_pipeline(
        profile=_profile(),
        research_question="best project management software",
        settings=_settings(),
        deps=deps,
    )

    # No usable data at all -> failed, but a report is still produced.
    assert state["status"] == "failed"
    assert state["error_flag"] is True
    assert "retrieval" in state["degraded_reason"]
    assert state["extracted_count"] == 0
    assert state["report"].report_summary  # partial report, not a crash
    assert state["report"].report_json["summary"]["degraded"] is True

    # The fallback node ran; analysis did not.
    executed = [n.node for n in state["metrics"].nodes]
    assert FALLBACK in executed
    assert ANALYZE_DATA not in executed


# --------------------------------------------------------------------------- #
# Partial run — some calls fail, usable data remains
# --------------------------------------------------------------------------- #
def _partial_failing_client() -> DataForSeoClient:
    """Fail only the keyword_metrics call; SERP / AI / LLM lookups still succeed."""

    def selective(_path: str, payload: dict[str, Any]) -> None:
        if "keywords" in payload:  # keyword_metrics payload shape
            raise httpx.ConnectTimeout("simulated timeout for keyword_metrics")

    return DataForSeoClient(settings=_settings(), retry_policy=_FAST, mock_hook=selective)


def test_partial_retrieval_failure_flags_partial() -> None:
    deps = _deps(_partial_failing_client())
    state = run_pipeline(
        profile=_profile(),
        research_question="best project management software",
        settings=_settings(),
        deps=deps,
    )

    assert state["status"] == "partial"
    assert state["error_flag"] is True
    assert state["extracted_count"] > 0  # SERP/AI/LLM data still normalized
    assert state["report"].report_json["summary"]["degraded"] is True
    # Analysis still ran on the usable data.
    assert ANALYZE_DATA in [n.node for n in state["metrics"].nodes]


# --------------------------------------------------------------------------- #
# Conditional routers (unit)
# --------------------------------------------------------------------------- #
def test_route_after_plan() -> None:
    valid = RetrievalPlan(research_question="q", calls=(_dummy_call(),))
    assert route_after_plan({"plan": valid}) == RETRIEVE_DATA
    assert route_after_plan({"plan": RetrievalPlan(research_question="q")}) == FALLBACK
    assert route_after_plan({}) == FALLBACK


def test_route_after_retrieve() -> None:
    from app.tools.base import ToolResult

    ok = RetrievalOutcome(results=(ToolResult.success("t", {}, {}),))
    empty = RetrievalOutcome(results=())
    assert route_after_retrieve({"retrieval": ok}) == NORMALIZE_DATA
    assert route_after_retrieve({"retrieval": empty}) == FALLBACK
    assert route_after_retrieve({}) == FALLBACK


def test_route_after_normalize() -> None:
    assert route_after_normalize({"extracted_count": 3}) == ANALYZE_DATA
    assert route_after_normalize({"extracted_count": 0}) == FALLBACK
    assert route_after_normalize({}) == FALLBACK


def _dummy_call():  # type: ignore[no-untyped-def]
    from app.agents.types import PlannedCall

    return PlannedCall(tool="keyword_metrics", args={"keywords": ["x"]}, rationale="r")


# --------------------------------------------------------------------------- #
# Compiled graph shape
# --------------------------------------------------------------------------- #
def test_compiled_graph_has_named_nodes() -> None:
    deps = _deps(DataForSeoClient(settings=_settings(), retry_policy=_FAST))
    graph = build_graph(deps)
    node_names = set(graph.get_graph().nodes)
    for name in (
        PLAN_QUERIES,
        RETRIEVE_DATA,
        NORMALIZE_DATA,
        ANALYZE_DATA,
        BUILD_REPORT,
        FALLBACK,
    ):
        assert name in node_names
