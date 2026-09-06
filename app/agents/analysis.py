"""Analysis / Synthesis agent — agent #4.

Its ONE job: reason over the normalized records to produce ranked
:class:`~app.agents.types.Insight` objects and content
:class:`~app.agents.types.RecommendationDraft` objects.

The numeric ``opportunity_score`` is computed **deterministically** by
:func:`opportunity_score` (documented below) — the model never invents or
overrides it (spec §4.2 / R31). The model is used only to add an optional
qualitative narrative; a deterministic narrative is used when no model is
available, so runs are reproducible by default.

``opportunity_score`` (bounded to ``[0, 1]``) rewards high-demand, low-difficulty
keywords where the brand is not yet visible::

    volume_norm     = min(estimated_search_volume / OPP_VOLUME_CAP, 1)   # demand
    difficulty_ease = 1 - (competitive_difficulty / 100)                 # easier = better
    visibility_gap  = 0.0 if domain_visible else 1.0                     # missing = opportunity

    opportunity_score = round(
          OPP_WEIGHT_VOLUME     * volume_norm
        + OPP_WEIGHT_DIFFICULTY * difficulty_ease
        + OPP_WEIGHT_GAP        * visibility_gap, 4)

The weights (default ``0.4 / 0.3 / 0.3``) and the volume cap live in
:class:`~app.config.Settings` and must sum to ``1.0``.

Atomicity guarantees (spec §3.2):
- Does NOT call tools, re-fetch data, or format the final report document.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.agents.types import (
    AnalysisResult,
    Insight,
    NormalizedQuery,
    ProfileContext,
    RecommendationDraft,
)
from app.config import Settings, get_settings
from app.db.models import ContentType, Priority, VisibilityStatus
from app.llm.base import LLMClient, Message
from app.llm.prompts import get_prompt
from app.observability.logging import get_logger

_logger = get_logger("agent.analysis")

_HIGH_PRIORITY_THRESHOLD = 0.66
_MEDIUM_PRIORITY_THRESHOLD = 0.40

_QUESTION_PREFIXES = (
    "how",
    "what",
    "why",
    "when",
    "where",
    "which",
    "who",
    "is",
    "are",
    "can",
    "do",
    "does",
)
_COMMERCIAL_TERMS = (
    "best",
    "top",
    "vs",
    "versus",
    "alternative",
    "alternatives",
    "software",
    "tool",
    "tools",
    "platform",
    "pricing",
    "price",
    "review",
    "reviews",
    "compare",
    "comparison",
)


def opportunity_score(
    *,
    estimated_search_volume: int,
    competitive_difficulty: int,
    domain_visible: bool,
    settings: Settings,
) -> float:
    """Compute the deterministic opportunity score in ``[0, 1]`` (see module docs)."""
    cap = settings.opp_volume_cap
    volume_norm = min(max(estimated_search_volume, 0) / cap, 1.0) if cap > 0 else 0.0
    difficulty = min(max(competitive_difficulty, 0), 100)
    difficulty_ease = 1.0 - (difficulty / 100.0)
    visibility_gap = 0.0 if domain_visible else 1.0

    score = (
        settings.opp_weight_volume * volume_norm
        + settings.opp_weight_difficulty * difficulty_ease
        + settings.opp_weight_gap * visibility_gap
    )
    return round(min(1.0, max(0.0, score)), 4)


class AnalysisAgent:
    """Score and rank normalized queries, then draft content recommendations."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        llm: LLMClient | None = None,
        max_recommendations: int = 5,
    ) -> None:
        self._settings = settings or get_settings()
        self._llm = llm
        self._max_recommendations = max(0, max_recommendations)

    def run(self, normalized: Sequence[NormalizedQuery], profile: ProfileContext) -> AnalysisResult:
        """Produce ranked insights, recommendations, and a qualitative narrative."""
        insights = self._score_and_rank(normalized)
        recommendations = self._draft_recommendations(insights)
        narrative = self._narrate(insights, profile)
        _logger.info(
            "agent.analysis.done",
            insights=len(insights),
            recommendations=len(recommendations),
        )
        return AnalysisResult(
            insights=tuple(insights),
            recommendations=tuple(recommendations),
            narrative=narrative,
        )

    # --- scoring --------------------------------------------------------- #
    def _score_and_rank(self, normalized: Sequence[NormalizedQuery]) -> list[Insight]:
        insights = [self._to_insight(record) for record in normalized]
        # Sort by opportunity (desc), then demand (desc) as a stable tie-breaker.
        insights.sort(
            key=lambda i: (i.opportunity_score, i.estimated_search_volume),
            reverse=True,
        )
        return insights

    def _to_insight(self, record: NormalizedQuery) -> Insight:
        score = opportunity_score(
            estimated_search_volume=record.estimated_search_volume,
            competitive_difficulty=record.competitive_difficulty,
            domain_visible=record.domain_visible,
            settings=self._settings,
        )
        return Insight(
            query_text=record.query_text,
            opportunity_score=score,
            estimated_search_volume=record.estimated_search_volume,
            competitive_difficulty=record.competitive_difficulty,
            domain_visible=record.domain_visible,
            visibility_position=record.visibility_position,
            visibility_status=record.visibility_status,
            rationale=self._rationale_for(record, score),
        )

    @staticmethod
    def _rationale_for(record: NormalizedQuery, score: float) -> str:
        """A concise, factual explanation of why a query scores the way it does."""
        demand = (
            f"~{record.estimated_search_volume:,} searches/mo"
            if record.estimated_search_volume
            else "low/unknown demand"
        )
        difficulty = f"difficulty {record.competitive_difficulty}/100"
        if record.visibility_status is VisibilityStatus.VISIBLE:
            position = (
                f" at position {record.visibility_position}"
                if record.visibility_position is not None
                else ""
            )
            visibility = f"the domain is already visible{position}"
        elif record.visibility_status is VisibilityStatus.NOT_VISIBLE:
            visibility = "the domain is not visible — an open gap"
        else:
            visibility = "visibility is unknown"
        return f"{demand}, {difficulty}; {visibility} (opportunity {score:.2f})."

    # --- recommendations ------------------------------------------------- #
    def _draft_recommendations(self, insights: Sequence[Insight]) -> list[RecommendationDraft]:
        drafts: list[RecommendationDraft] = []
        for insight in insights[: self._max_recommendations]:
            content_type = self._content_type_for(insight.query_text)
            priority = self._priority_for(insight.opportunity_score)
            gap = (
                "the brand is not yet visible"
                if not insight.domain_visible
                else "presence can be strengthened"
            )
            drafts.append(
                RecommendationDraft(
                    target_query_text=insight.query_text,
                    content_type=content_type,
                    title=self._title_for(insight.query_text, content_type),
                    rationale=(
                        f"Targets '{insight.query_text}' where {gap}; "
                        f"opportunity score {insight.opportunity_score:.2f}."
                    ),
                    target_keywords=(insight.query_text,),
                    priority=priority,
                )
            )
        return drafts

    @staticmethod
    def _content_type_for(query: str) -> ContentType:
        text = query.strip().lower()
        first_word = text.split(" ", 1)[0] if text else ""
        if text.endswith("?") or first_word in _QUESTION_PREFIXES:
            return ContentType.FAQ
        if any(term in text.split() or term in text for term in _COMMERCIAL_TERMS):
            return ContentType.LANDING_PAGE
        return ContentType.BLOG_POST

    @staticmethod
    def _priority_for(score: float) -> Priority:
        if score >= _HIGH_PRIORITY_THRESHOLD:
            return Priority.HIGH
        if score >= _MEDIUM_PRIORITY_THRESHOLD:
            return Priority.MEDIUM
        return Priority.LOW

    @staticmethod
    def _title_for(query: str, content_type: ContentType) -> str:
        clean = query.strip()
        if content_type is ContentType.FAQ:
            base = clean if clean.endswith("?") else f"{clean}?"
            return f"FAQ: {base[0].upper() + base[1:]}" if base else "FAQ"
        if content_type is ContentType.LANDING_PAGE:
            return f"{clean.title()} — Comparison & Buyer's Guide"
        return f"{clean.title()}: A Complete Guide"

    # --- narrative (optional LLM) ---------------------------------------- #
    def _narrate(self, insights: Sequence[Insight], profile: ProfileContext) -> str:
        """A short qualitative synthesis: model-written when available, else derived."""
        if self._llm is not None and insights:
            narrative = self._narrate_via_llm(insights, profile)
            if narrative:
                return narrative
        return self._deterministic_narrative(insights, profile)

    def _narrate_via_llm(self, insights: Sequence[Insight], profile: ProfileContext) -> str:
        top = insights[:5]
        lines = "\n".join(
            f"- {i.query_text}: score {i.opportunity_score:.2f}, "
            f"volume {i.estimated_search_volume}, difficulty {i.competitive_difficulty}, "
            f"{i.visibility_status.value}"
            for i in top
        )
        messages = [
            Message.system(get_prompt("analysis")),
            Message.user(
                f"Brand: {profile.name} ({profile.domain}).\n"
                f"Top scored queries:\n{lines}\n\n"
                "In 2-3 sentences, summarize where the brand is visible, where it is "
                "missing, and the biggest opportunities. Do not restate the numbers."
            ),
        ]
        try:
            response = self._llm.complete(messages) if self._llm else None
        except Exception as exc:  # narrative is best-effort; never break a run
            _logger.warning("agent.analysis.llm_failed", error=type(exc).__name__)
            return ""
        return response.content.strip() if response else ""

    @staticmethod
    def _deterministic_narrative(insights: Sequence[Insight], profile: ProfileContext) -> str:
        if not insights:
            return (
                f"No queries were discovered for {profile.name}, "
                "so no opportunities could be identified."
            )
        gaps = [i for i in insights if not i.domain_visible]
        visible = [i for i in insights if i.domain_visible]
        top = insights[0]
        return (
            f"Analyzed {len(insights)} queries for {profile.name}: "
            f"{len(visible)} where the domain is already visible and {len(gaps)} open gaps. "
            f"The strongest opportunity is '{top.query_text}' "
            f"(opportunity score {top.opportunity_score:.2f})."
        )


__all__ = ["AnalysisAgent", "opportunity_score"]
