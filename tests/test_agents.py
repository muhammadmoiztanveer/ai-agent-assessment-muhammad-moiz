"""Phase 6 tests: the five atomic agents.

Each agent is exercised in isolation to prove it does exactly one job (spec §3.2):

- Planner: LLM-driven tool selection *and* a deterministic fallback plan; unknown
  tools filtered; plan bounded.
- Retrieval: executes planned calls, surfacing unknown-tool and invalid-argument
  failures as classified errors without crashing.
- Extraction: deterministic parsing of DataForSEO envelopes into clean records,
  including brand-domain visibility detection.
- Analysis: the opportunity_score formula (correctness + [0, 1] bounds + ordering)
  plus recommendation heuristics and narrative fallback.
- Report: assembly of the structured report + human summary, including the
  partial/degraded note.

All tests are hermetic: no network, no API key.
"""

from __future__ import annotations

from app.agents.analysis import AnalysisAgent, opportunity_score
from app.agents.extraction import ExtractionAgent
from app.agents.planner import PlannerAgent
from app.agents.report import ReportAgent
from app.agents.retrieval import RetrievalAgent
from app.agents.types import (
    Insight,
    NormalizedQuery,
    PlannedCall,
    ProfileContext,
    RetrievalPlan,
)
from app.config import Settings
from app.db.models import ContentType, Priority, VisibilityStatus
from app.integrations.dataforseo.client import DataForSeoClient
from app.llm.base import LLMResponse, ToolCall
from app.llm.mock import ScriptedLLMClient
from app.resilience.retry import RetryPolicy
from app.tools.base import ToolResult
from app.tools.dataforseo_tools import build_dataforseo_tools

_FAST = RetryPolicy(max_attempts=2, base_delay_s=0.0, max_delay_s=0.0, jitter=False)


def _profile() -> ProfileContext:
    return ProfileContext(
        name="Surfer SEO",
        domain="https://www.surferseo.com",
        industry="SEO",
        competitors=("ahrefs.com", "semrush.com"),
    )


def _tools() -> dict[str, object]:
    return build_dataforseo_tools(DataForSeoClient(retry_policy=_FAST))


def _settings() -> Settings:
    # Explicit defaults so the test does not depend on ambient env / .env.
    return Settings(
        OPP_WEIGHT_VOLUME=0.4,
        OPP_WEIGHT_DIFFICULTY=0.3,
        OPP_WEIGHT_GAP=0.3,
        OPP_VOLUME_CAP=10_000,
    )


# --------------------------------------------------------------------------- #
# Planner
# --------------------------------------------------------------------------- #
def test_planner_deterministic_fallback_is_grounded_in_inputs() -> None:
    # An empty scripted client returns no tool calls -> deterministic plan.
    planner = PlannerAgent(llm=ScriptedLLMClient(), tools=_tools())  # type: ignore[arg-type]
    plan = planner.run(_profile(), "best project management software")

    assert plan.is_valid
    tools_used = {c.tool for c in plan.calls}
    assert "keyword_metrics" in tools_used
    assert "serp_organic_search" in tools_used
    # The research question is grounded into at least one SERP lookup.
    serp_keywords = [c.args["keyword"] for c in plan.calls if c.tool == "serp_organic_search"]
    assert "best project management software" in serp_keywords
    # Every planned call targets a real tool.
    known = set(_tools())
    assert all(c.tool in known for c in plan.calls)


def test_planner_uses_llm_tool_calls_when_offered() -> None:
    scripted = ScriptedLLMClient(
        responses=[
            LLMResponse(
                tool_calls=(
                    ToolCall(name="serp_organic_search", args={"keyword": "surfer seo"}),
                    ToolCall(name="keyword_metrics", args={"keywords": ["surfer seo"]}),
                    ToolCall(name="bogus_tool", args={}),  # must be filtered out
                )
            )
        ]
    )
    planner = PlannerAgent(llm=scripted, tools=_tools())  # type: ignore[arg-type]
    plan = planner.run(_profile(), "surfer seo")

    assert [c.tool for c in plan.calls] == ["serp_organic_search", "keyword_metrics"]
    assert all("Selected by the planning model" in c.rationale for c in plan.calls)


def test_planner_bounds_number_of_calls() -> None:
    planner = PlannerAgent(llm=ScriptedLLMClient(), tools=_tools(), max_calls=2)  # type: ignore[arg-type]
    plan = planner.run(_profile(), "best crm software")
    assert plan.call_count == 2


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #
def test_retrieval_executes_and_classifies_failures() -> None:
    agent = RetrievalAgent(tools=_tools())  # type: ignore[arg-type]
    plan = RetrievalPlan(
        research_question="q",
        calls=(
            PlannedCall("serp_organic_search", {"keyword": "valid keyword"}, "ok"),
            PlannedCall("serp_organic_search", {"keyword": ""}, "invalid args"),
            PlannedCall("nonexistent_tool", {}, "unknown"),
        ),
    )
    outcome = agent.run(plan)

    assert outcome.has_usable_results  # the valid call succeeded
    assert len(outcome.ok_results) == 1
    error_codes = {e.code for e in outcome.errors}
    assert "invalid_tool_args" in error_codes  # blank keyword rejected before call
    assert "unknown_tool" in error_codes
    # Retrieval returns raw ToolResults only — no normalization happened.
    assert all(isinstance(r, ToolResult) for r in outcome.results)


def test_retrieval_all_failures_has_no_usable_results() -> None:
    agent = RetrievalAgent(tools=_tools())  # type: ignore[arg-type]
    plan = RetrievalPlan(
        research_question="q",
        calls=(PlannedCall("nonexistent_tool", {}, "unknown"),),
    )
    outcome = agent.run(plan)
    assert not outcome.has_usable_results
    assert len(outcome.errors) == 1


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def _kw_metrics_envelope() -> dict:
    return {
        "tasks": [
            {
                "result": [
                    {
                        "items": [
                            {
                                "keyword": "best crm",
                                "keyword_info": {"search_volume": 12000},
                                "keyword_properties": {"keyword_difficulty": 20},
                            },
                            {
                                "keyword": "crm tools",
                                "keyword_info": {"search_volume": 3000},
                                "keyword_properties": {"keyword_difficulty": 80},
                            },
                        ]
                    }
                ]
            }
        ]
    }


def _serp_envelope(keyword: str, items: list[dict]) -> dict:
    return {"tasks": [{"result": [{"keyword": keyword, "items": items}]}]}


def test_extraction_normalizes_and_detects_visibility() -> None:
    results = [
        ToolResult.success("keyword_metrics", _kw_metrics_envelope(), {}),
        ToolResult.success(
            "serp_organic_search",
            _serp_envelope(
                "best crm",
                [
                    {"domain": "competitor.com", "rank_absolute": 1},
                    {"domain": "www.surferseo.com", "rank_absolute": 3},
                ],
            ),
            {},
        ),
        ToolResult.success(
            "serp_organic_search",
            _serp_envelope("crm tools", [{"domain": "other.com", "rank_absolute": 1}]),
            {},
        ),
    ]
    records = {r.query_text: r for r in ExtractionAgent().run(results, _profile())}

    assert set(records) == {"best crm", "crm tools"}

    best = records["best crm"]
    assert best.estimated_search_volume == 12000
    assert best.competitive_difficulty == 20
    assert best.domain_visible is True
    assert best.visibility_position == 3
    assert best.visibility_status is VisibilityStatus.VISIBLE

    tools_kw = records["crm tools"]
    assert tools_kw.domain_visible is False
    assert tools_kw.visibility_status is VisibilityStatus.NOT_VISIBLE
    assert tools_kw.visibility_position is None


def test_extraction_status_unknown_without_visibility_signal() -> None:
    # Only keyword metrics, no SERP/AI/LLM lookup -> visibility unknown.
    records = ExtractionAgent().run(
        [ToolResult.success("keyword_metrics", _kw_metrics_envelope(), {})],
        _profile(),
    )
    assert all(r.visibility_status is VisibilityStatus.UNKNOWN for r in records)


def test_extraction_ignores_failed_results() -> None:
    from app.resilience.errors import ClassifiedError

    failed = ToolResult.failure(
        "serp_organic_search",
        ClassifiedError(code="boom", retryable=True, message="down"),
    )
    assert ExtractionAgent().run([failed], _profile()) == []


# --------------------------------------------------------------------------- #
# Analysis — opportunity_score
# --------------------------------------------------------------------------- #
def test_opportunity_score_matches_documented_formula() -> None:
    settings = _settings()
    # volume_norm=1.0, ease=0.8, gap=0 -> 0.4*1 + 0.3*0.8 + 0 = 0.64
    assert (
        opportunity_score(
            estimated_search_volume=12000,
            competitive_difficulty=20,
            domain_visible=True,
            settings=settings,
        )
        == 0.64
    )
    # volume_norm=0.3, ease=0.2, gap=1 -> 0.12 + 0.06 + 0.3 = 0.48
    assert (
        opportunity_score(
            estimated_search_volume=3000,
            competitive_difficulty=80,
            domain_visible=False,
            settings=settings,
        )
        == 0.48
    )


def test_opportunity_score_is_bounded() -> None:
    settings = _settings()
    best = opportunity_score(
        estimated_search_volume=10_000_000,
        competitive_difficulty=0,
        domain_visible=False,
        settings=settings,
    )
    worst = opportunity_score(
        estimated_search_volume=0,
        competitive_difficulty=100,
        domain_visible=True,
        settings=settings,
    )
    assert best == 1.0
    assert worst == 0.0


def test_analysis_ranks_and_recommends() -> None:
    normalized = [
        NormalizedQuery(
            query_text="crm tools",
            estimated_search_volume=3000,
            competitive_difficulty=80,
            domain_visible=False,
            visibility_status=VisibilityStatus.NOT_VISIBLE,
        ),
        NormalizedQuery(
            query_text="best crm",
            estimated_search_volume=12000,
            competitive_difficulty=20,
            domain_visible=True,
            visibility_position=3,
            visibility_status=VisibilityStatus.VISIBLE,
        ),
    ]
    result = AnalysisAgent(settings=_settings()).run(normalized, _profile())

    # Ranked by opportunity_score desc: best crm (0.64) before crm tools (0.48).
    assert [i.query_text for i in result.insights] == ["best crm", "crm tools"]
    assert result.insights[0].opportunity_score == 0.64
    # A recommendation is drafted per top query.
    assert len(result.recommendations) == 2
    # "best crm" is commercial -> landing page; score 0.64 -> medium priority.
    top_rec = result.recommendations[0]
    assert top_rec.content_type is ContentType.LANDING_PAGE
    assert top_rec.priority is Priority.MEDIUM
    # Deterministic narrative mentions the brand.
    assert "Surfer SEO" in result.narrative


def test_analysis_content_type_heuristics() -> None:
    agent = AnalysisAgent(settings=_settings())
    faq = NormalizedQuery(query_text="how to rank on google?")
    blog = NormalizedQuery(query_text="content marketing ideas")
    result_faq = agent.run([faq], _profile())
    result_blog = agent.run([blog], _profile())
    assert result_faq.recommendations[0].content_type is ContentType.FAQ
    assert result_blog.recommendations[0].content_type is ContentType.BLOG_POST


def test_analysis_uses_llm_narrative_when_available() -> None:
    scripted = ScriptedLLMClient(responses=[LLMResponse(content="Custom analyst narrative.")])
    normalized = [NormalizedQuery(query_text="best crm", estimated_search_volume=100)]
    result = AnalysisAgent(settings=_settings(), llm=scripted).run(normalized, _profile())
    assert result.narrative == "Custom analyst narrative."


def test_analysis_handles_no_data() -> None:
    result = AnalysisAgent(settings=_settings()).run([], _profile())
    assert result.insights == ()
    assert result.recommendations == ()
    assert "No queries were discovered" in result.narrative


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def _insight(score: float, *, visible: bool = False) -> Insight:
    return Insight(
        query_text="best crm",
        opportunity_score=score,
        estimated_search_volume=12000,
        competitive_difficulty=20,
        domain_visible=visible,
        visibility_position=3 if visible else None,
        visibility_status=VisibilityStatus.VISIBLE if visible else VisibilityStatus.NOT_VISIBLE,
        rationale="because",
    )


def test_report_assembles_structured_json_and_summary() -> None:
    report = ReportAgent().run(
        profile=_profile(),
        insights=[_insight(0.64)],
        recommendations=[],
        extracted_count=1,
    )
    assert report.report_json["profile"]["name"] == "Surfer SEO"
    assert report.report_json["summary"]["extracted_records"] == 1
    assert report.report_json["summary"]["total_queries"] == 1
    assert len(report.report_json["top_insights"]) == 1
    assert "Surfer SEO" in report.report_summary


def test_report_degraded_note_and_empty_case() -> None:
    degraded = ReportAgent().run(
        profile=_profile(),
        insights=[_insight(0.5)],
        recommendations=[],
        extracted_count=0,
        degraded=True,
        degraded_reason="all retrieval failed",
    )
    assert "partial result" in degraded.report_summary
    assert "all retrieval failed" in degraded.report_summary

    empty = ReportAgent().run(
        profile=_profile(),
        insights=[],
        recommendations=[],
        extracted_count=0,
    )
    assert "No search opportunities" in empty.report_summary


def test_report_uses_llm_summary_when_available() -> None:
    scripted = ScriptedLLMClient(responses=[LLMResponse(content="Executive summary here.")])
    report = ReportAgent(llm=scripted).run(
        profile=_profile(),
        insights=[_insight(0.7)],
        recommendations=[],
        extracted_count=1,
    )
    assert report.report_summary == "Executive summary here."
