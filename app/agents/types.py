"""Typed value objects exchanged between the five atomic agents.

These are the contracts that keep each agent's responsibility crisp and its inputs
and outputs explicit (spec §3.2). They are deliberately plain, immutable
dataclasses — framework-neutral and JSON-serializable via ``as_dict`` — so agents
are testable in isolation and the LangGraph node wrappers (Phase 7) can move them
in and out of the shared graph state without any coupling to the graph itself.

Flow of data through the pipeline::

    ProfileContext + research_question
        → (Planner)     RetrievalPlan(calls=[PlannedCall, ...])
        → (Retrieval)   RetrievalOutcome(results=[ToolResult, ...])
        → (Extraction)  [NormalizedQuery, ...]
        → (Analysis)    AnalysisResult(insights, recommendations, narrative)
        → (Report)      Report(report_json, report_summary)

Enum-valued fields reuse the persistence enums (:mod:`app.db.models`) so an
agent's output maps onto a database row with zero translation or drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.db.models import ContentType, Priority, VisibilityStatus
from app.resilience.errors import ClassifiedError
from app.tools.base import ToolResult


def normalize_domain(domain: str) -> str:
    """Reduce a domain/URL to a bare, comparable host (lowercase, no scheme/www)."""
    host = domain.strip().lower()
    host = host.removeprefix("https://").removeprefix("http://").removeprefix("www.")
    return host.split("/", 1)[0]


@dataclass(frozen=True, slots=True)
class ProfileContext:
    """The brand profile an analysis run is about (agent-facing view of a Profile)."""

    name: str
    domain: str
    industry: str | None = None
    description: str | None = None
    competitors: tuple[str, ...] = ()

    @property
    def host(self) -> str:
        """The profile's domain reduced to a bare host for matching."""
        return normalize_domain(self.domain)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "domain": self.domain,
            "industry": self.industry,
            "description": self.description,
            "competitors": list(self.competitors),
        }


@dataclass(frozen=True, slots=True)
class PlannedCall:
    """A single intended tool call the Planner decided is needed."""

    tool: str
    args: dict[str, Any]
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": self.args, "rationale": self.rationale}


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    """An ordered set of planned tool calls plus the question they serve."""

    research_question: str
    calls: tuple[PlannedCall, ...] = ()

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def is_valid(self) -> bool:
        """A plan is usable when it has at least one call."""
        return self.call_count > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "research_question": self.research_question,
            "call_count": self.call_count,
            "calls": [c.as_dict() for c in self.calls],
        }


@dataclass(frozen=True, slots=True)
class RetrievalOutcome:
    """The raw results of executing a plan, with failures kept alongside."""

    results: tuple[ToolResult, ...] = ()
    errors: tuple[ClassifiedError, ...] = ()

    @property
    def ok_results(self) -> tuple[ToolResult, ...]:
        return tuple(r for r in self.results if r.ok)

    @property
    def has_usable_results(self) -> bool:
        return any(r.ok for r in self.results)

    def as_dict(self) -> dict[str, Any]:
        return {
            "results": [r.as_dict() for r in self.results],
            "errors": [e.as_dict() for e in self.errors],
            "usable_count": len(self.ok_results),
        }


@dataclass(frozen=True, slots=True)
class NormalizedQuery:
    """A clean, schema-conformant record for one discovered query/keyword.

    Purely factual — no scores or judgements (those belong to Analysis).
    """

    query_text: str
    estimated_search_volume: int = 0
    competitive_difficulty: int = 0
    domain_visible: bool = False
    visibility_position: int | None = None
    visibility_status: VisibilityStatus = VisibilityStatus.UNKNOWN
    sources: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "query_text": self.query_text,
            "estimated_search_volume": self.estimated_search_volume,
            "competitive_difficulty": self.competitive_difficulty,
            "domain_visible": self.domain_visible,
            "visibility_position": self.visibility_position,
            "visibility_status": self.visibility_status.value,
            "sources": list(self.sources),
        }


@dataclass(frozen=True, slots=True)
class Insight:
    """A scored, ranked query with a qualitative rationale (Analysis output)."""

    query_text: str
    opportunity_score: float
    estimated_search_volume: int
    competitive_difficulty: int
    domain_visible: bool
    visibility_position: int | None
    visibility_status: VisibilityStatus
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "query_text": self.query_text,
            "opportunity_score": self.opportunity_score,
            "estimated_search_volume": self.estimated_search_volume,
            "competitive_difficulty": self.competitive_difficulty,
            "domain_visible": self.domain_visible,
            "visibility_position": self.visibility_position,
            "visibility_status": self.visibility_status.value,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class RecommendationDraft:
    """A proposed piece of content targeting a specific query (Analysis output)."""

    target_query_text: str
    content_type: ContentType
    title: str
    rationale: str
    target_keywords: tuple[str, ...]
    priority: Priority

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_query_text": self.target_query_text,
            "content_type": self.content_type.value,
            "title": self.title,
            "rationale": self.rationale,
            "target_keywords": list(self.target_keywords),
            "priority": self.priority.value,
        }


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Everything the Analysis agent produces from the normalized records."""

    insights: tuple[Insight, ...] = ()
    recommendations: tuple[RecommendationDraft, ...] = ()
    narrative: str = ""

    def top_insights(self, limit: int) -> list[Insight]:
        return list(self.insights[: max(limit, 0)])

    def as_dict(self) -> dict[str, Any]:
        return {
            "insights": [i.as_dict() for i in self.insights],
            "recommendations": [r.as_dict() for r in self.recommendations],
            "narrative": self.narrative,
        }


@dataclass(frozen=True, slots=True)
class Report:
    """The final deliverable: a structured JSON report and a human summary."""

    report_json: dict[str, Any] = field(default_factory=dict)
    report_summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"report_json": self.report_json, "report_summary": self.report_summary}


__all__ = [
    "AnalysisResult",
    "Insight",
    "NormalizedQuery",
    "PlannedCall",
    "ProfileContext",
    "RecommendationDraft",
    "Report",
    "RetrievalOutcome",
    "RetrievalPlan",
    "normalize_domain",
]
