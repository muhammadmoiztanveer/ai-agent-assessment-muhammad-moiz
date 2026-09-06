"""Report agent — agent #5.

Its ONE job: assemble the final deliverable — a structured ``report_json`` and a
concise, human-readable ``report_summary`` — from what the Analysis agent
produced. The model, when available, writes the executive summary prose; a
deterministic summary is used otherwise so a run always returns readable output.

Atomicity guarantees (spec §3.2):
- Summarizes only what analysis provided. Does NOT call tools, re-score, or
  introduce new findings.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.agents.types import Insight, ProfileContext, RecommendationDraft, Report
from app.llm.base import LLMClient, Message
from app.llm.prompts import get_prompt
from app.observability.logging import get_logger

_logger = get_logger("agent.report")

_DEFAULT_TOP_N = 5


class ReportAgent:
    """Assemble the structured report and human-readable summary."""

    def __init__(self, *, llm: LLMClient | None = None, top_n: int = _DEFAULT_TOP_N) -> None:
        self._llm = llm
        self._top_n = max(1, top_n)

    def run(
        self,
        *,
        profile: ProfileContext,
        insights: Sequence[Insight],
        recommendations: Sequence[RecommendationDraft],
        extracted_count: int,
        analysis_narrative: str = "",
        degraded: bool = False,
        degraded_reason: str | None = None,
    ) -> Report:
        """Build the final report from analysis outputs."""
        top_insights = list(insights[: self._top_n])
        report_json: dict[str, Any] = {
            "profile": profile.as_dict(),
            "summary": {
                "extracted_records": extracted_count,
                "total_queries": len(insights),
                "opportunities": sum(1 for i in insights if not i.domain_visible),
                "recommendations": len(recommendations),
                "degraded": degraded,
                "degraded_reason": degraded_reason,
            },
            "top_insights": [i.as_dict() for i in top_insights],
            "recommendations": [r.as_dict() for r in recommendations],
        }
        summary = self._summarize(
            profile=profile,
            top_insights=top_insights,
            recommendations=recommendations,
            analysis_narrative=analysis_narrative,
            degraded=degraded,
            degraded_reason=degraded_reason,
        )
        _logger.info("agent.report.done", degraded=degraded, top_insights=len(top_insights))
        return Report(report_json=report_json, report_summary=summary)

    # --- summary --------------------------------------------------------- #
    def _summarize(
        self,
        *,
        profile: ProfileContext,
        top_insights: Sequence[Insight],
        recommendations: Sequence[RecommendationDraft],
        analysis_narrative: str,
        degraded: bool,
        degraded_reason: str | None,
    ) -> str:
        if self._llm is not None and top_insights:
            summary = self._summarize_via_llm(
                profile, top_insights, recommendations, analysis_narrative
            )
            if summary:
                return self._with_degraded_note(summary, degraded, degraded_reason)
        deterministic = self._deterministic_summary(
            profile, top_insights, recommendations, analysis_narrative
        )
        return self._with_degraded_note(deterministic, degraded, degraded_reason)

    def _summarize_via_llm(
        self,
        profile: ProfileContext,
        top_insights: Sequence[Insight],
        recommendations: Sequence[RecommendationDraft],
        analysis_narrative: str,
    ) -> str:
        insight_lines = "\n".join(
            f"- {i.query_text} (opportunity {i.opportunity_score:.2f}, {i.visibility_status.value})"
            for i in top_insights
        )
        rec_lines = "\n".join(
            f"- {r.content_type.value}: {r.title} [{r.priority.value}]" for r in recommendations
        )
        messages = [
            Message.system(get_prompt("report")),
            Message.user(
                f"Brand: {profile.name} ({profile.domain}).\n"
                f"Analyst note: {analysis_narrative or 'n/a'}\n\n"
                f"Top opportunities:\n{insight_lines or '- none'}\n\n"
                f"Recommendations:\n{rec_lines or '- none'}\n\n"
                "Write a concise executive summary (3-5 sentences) a marketing lead can act on."
            ),
        ]
        try:
            response = self._llm.complete(messages) if self._llm else None
        except Exception as exc:  # summary is best-effort; never break a run
            _logger.warning("agent.report.llm_failed", error=type(exc).__name__)
            return ""
        return response.content.strip() if response else ""

    @staticmethod
    def _deterministic_summary(
        profile: ProfileContext,
        top_insights: Sequence[Insight],
        recommendations: Sequence[RecommendationDraft],
        analysis_narrative: str,
    ) -> str:
        if not top_insights:
            return (
                f"No search opportunities were identified for {profile.name} "
                f"({profile.domain}) in this run."
            )
        top = top_insights[0]
        # Use the analyst narrative as the lead when present; otherwise state the
        # top opportunity directly (avoids repeating what the narrative already says).
        lead = analysis_narrative or (
            f"Search-visibility analysis for {profile.name} ({profile.domain}). "
            f"The top opportunity is '{top.query_text}' with an opportunity score of "
            f"{top.opportunity_score:.2f}."
        )
        rec_note = (
            f"{len(recommendations)} content recommendation(s) were drafted, "
            f'led by "{recommendations[0].title}".'
            if recommendations
            else "No content recommendations were drafted."
        )
        return f"{lead} {rec_note}"

    @staticmethod
    def _with_degraded_note(summary: str, degraded: bool, degraded_reason: str | None) -> str:
        if not degraded:
            return summary
        reason = degraded_reason or "some data was unavailable"
        return f"{summary} Note: this is a partial result ({reason})."


__all__ = ["ReportAgent"]
