"""Query Planner — agent #1.

Its ONE job: turn a brand profile and a research question into a
:class:`~app.agents.types.RetrievalPlan` — an ordered list of intended tool calls
(which DataForSEO endpoint, with which arguments) and a short rationale for each.

The planner **decides**; it never fetches. The language model is offered the tool
schemas and chooses which tools to call and with what arguments (spec §3.3 / R7);
the planner maps those choices into a bounded, validated plan. When no model is
available (the keyless/mock path) or the model proposes nothing usable, a
deterministic fallback plan — grounded in the profile and question — is produced,
so a run always has a sensible plan to execute.

Atomicity guarantees (spec §3.2):
- Does NOT call DataForSEO or execute any tool.
- Does NOT normalize, score, or summarize.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.agents.types import PlannedCall, ProfileContext, RetrievalPlan
from app.llm.base import LLMClient, Message, specs_from_tools
from app.llm.prompts import get_prompt
from app.observability.logging import get_logger
from app.tools.base import ValidatedTool

_logger = get_logger("agent.planner")

# A conservative ceiling so a run never fans out into an unbounded number of calls.
_DEFAULT_MAX_CALLS = 8
# How many seed keywords the deterministic plan derives from the profile/question.
_MAX_SEED_KEYWORDS = 4


class PlannerAgent:
    """Plan the retrieval calls needed to answer a research question."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        tools: Mapping[str, ValidatedTool],
        max_calls: int = _DEFAULT_MAX_CALLS,
    ) -> None:
        self._llm = llm
        self._tools = dict(tools)
        self._specs = specs_from_tools(list(self._tools.values()))
        self._max_calls = max(1, max_calls)

    def run(self, profile: ProfileContext, research_question: str) -> RetrievalPlan:
        """Produce a bounded retrieval plan for ``research_question``."""
        question = research_question.strip()
        calls = self._plan_via_llm(profile, question)
        source = "llm"
        if not calls:
            calls = self._deterministic_plan(profile, question)
            source = "deterministic"

        bounded = self._bound(calls)
        _logger.info(
            "agent.planner.plan",
            source=source,
            planned_calls=len(bounded),
            research_question=question,
        )
        return RetrievalPlan(research_question=question, calls=tuple(bounded))

    # --- LLM-driven planning --------------------------------------------- #
    def _plan_via_llm(self, profile: ProfileContext, question: str) -> list[PlannedCall]:
        """Ask the model to choose tool calls; map valid choices into the plan.

        Any failure here is non-fatal: the caller falls back to a deterministic
        plan, so a flaky model can never break planning.
        """
        messages = [
            Message.system(get_prompt("planner")),
            Message.user(self._planning_prompt(profile, question)),
        ]
        try:
            response = self._llm.complete(messages, tools=self._specs)
        except Exception as exc:  # planning must degrade to fallback, not crash
            _logger.warning("agent.planner.llm_failed", error=type(exc).__name__)
            return []

        calls: list[PlannedCall] = []
        for call in response.tool_calls:
            if call.name in self._tools and isinstance(call.args, dict):
                calls.append(
                    PlannedCall(
                        tool=call.name,
                        args=dict(call.args),
                        rationale="Selected by the planning model.",
                    )
                )
        return calls

    @staticmethod
    def _planning_prompt(profile: ProfileContext, question: str) -> str:
        competitors = ", ".join(profile.competitors) if profile.competitors else "none provided"
        industry = profile.industry or "unspecified"
        return (
            f"Brand: {profile.name} (domain: {profile.domain})\n"
            f"Industry: {industry}\n"
            f"Competitors: {competitors}\n"
            f"Research question: {question}\n\n"
            "Decide which search and AI-visibility lookups are needed to answer the "
            "question, and call the appropriate tools with well-formed arguments."
        )

    # --- deterministic fallback ------------------------------------------ #
    def _deterministic_plan(self, profile: ProfileContext, question: str) -> list[PlannedCall]:
        """Build a sensible plan without a model, grounded in profile + question."""
        seeds = self._seed_keywords(profile, question)
        calls: list[PlannedCall] = []

        if "keyword_metrics" in self._tools and seeds:
            calls.append(
                PlannedCall(
                    tool="keyword_metrics",
                    args={"keywords": seeds},
                    rationale="Size search demand and difficulty for the seed keywords.",
                )
            )

        if "serp_organic_search" in self._tools:
            for keyword in seeds:
                calls.append(
                    PlannedCall(
                        tool="serp_organic_search",
                        args={"keyword": keyword},
                        rationale=f"Check organic search visibility for '{keyword}'.",
                    )
                )

        if "ai_overview_search" in self._tools and question:
            calls.append(
                PlannedCall(
                    tool="ai_overview_search",
                    args={"keyword": question},
                    rationale="Check visibility inside Google's AI Overview for the question.",
                )
            )

        if "llm_visibility_lookup" in self._tools and question:
            calls.append(
                PlannedCall(
                    tool="llm_visibility_lookup",
                    args={"prompt": question, "brand": profile.name},
                    rationale="Check whether the brand is cited in LLM assistant answers.",
                )
            )

        return calls

    @staticmethod
    def _seed_keywords(profile: ProfileContext, question: str) -> list[str]:
        """Derive a small, deterministic set of seed keywords from the inputs."""
        seeds: list[str] = []
        if question:
            seeds.append(question)
        if profile.industry:
            industry = profile.industry.strip().lower()
            seeds.extend(
                [
                    f"best {industry} software",
                    f"{industry} tools",
                    f"{industry} alternatives",
                ]
            )

        # De-duplicate case-insensitively while preserving order, then cap.
        seen: set[str] = set()
        unique: list[str] = []
        for keyword in seeds:
            key = keyword.strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(keyword.strip())
        return unique[:_MAX_SEED_KEYWORDS]

    def _bound(self, calls: list[PlannedCall]) -> list[PlannedCall]:
        """Drop calls for unknown tools and cap the total number of calls."""
        known = [c for c in calls if c.tool in self._tools]
        return known[: self._max_calls]


__all__ = ["PlannerAgent"]
