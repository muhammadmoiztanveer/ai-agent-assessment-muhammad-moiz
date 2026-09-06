"""DataForSEO tools — one :class:`ValidatedTool` per logical API call.

Each tool wraps exactly one client method (spec §3.4: "one tool per logical API
call", not a single catch-all "call DataForSEO" tool). Every tool validates its
arguments against a Pydantic schema before invoking the client, and returns a
:class:`~app.tools.base.ToolResult` so callers never have to guard against raw
exceptions.

:func:`build_dataforseo_tools` wires a client instance into a named registry the
retrieval agent and LLM layer consume.
"""

from __future__ import annotations

from app.integrations.dataforseo.client import DataForSeoClient
from app.tools.base import ValidatedTool
from app.tools.schemas import (
    AiOverviewSearchArgs,
    KeywordMetricsArgs,
    LlmVisibilityArgs,
    SerpOrganicSearchArgs,
)


def build_dataforseo_tools(client: DataForSeoClient) -> dict[str, ValidatedTool]:
    """Build the DataForSEO tool registry bound to ``client``.

    Returns a mapping of tool name → :class:`ValidatedTool`. Names are stable and
    used by the planner/retrieval agents and for LLM tool binding.
    """
    serp_organic_search = ValidatedTool(
        name="serp_organic_search",
        description=(
            "Fetch live Google organic search results for a keyword. Use to see which "
            "domains rank and whether a brand's domain appears in organic results."
        ),
        args_schema=SerpOrganicSearchArgs,
        func=lambda a: client.serp_organic_search(
            keyword=a.keyword,
            location_code=a.location_code,
            language_code=a.language_code,
            depth=a.depth,
        ),
    )

    ai_overview_search = ValidatedTool(
        name="ai_overview_search",
        description=(
            "Fetch the Google AI Overview / AI Mode answer block for a keyword, including "
            "the cited source domains. Use to assess visibility inside AI-generated answers."
        ),
        args_schema=AiOverviewSearchArgs,
        func=lambda a: client.ai_overview_search(
            keyword=a.keyword,
            location_code=a.location_code,
            language_code=a.language_code,
        ),
    )

    llm_visibility_lookup = ValidatedTool(
        name="llm_visibility_lookup",
        description=(
            "Check whether a brand is mentioned/cited in LLM assistant answers (e.g. ChatGPT, "
            "Gemini, Perplexity) for a given prompt."
        ),
        args_schema=LlmVisibilityArgs,
        func=lambda a: client.llm_visibility_lookup(
            prompt=a.prompt,
            brand=a.brand,
            models=a.models,
        ),
    )

    keyword_metrics = ValidatedTool(
        name="keyword_metrics",
        description=(
            "Fetch estimated monthly search volume and competitive difficulty for one or "
            "more keywords. Use to size demand and estimate ranking difficulty."
        ),
        args_schema=KeywordMetricsArgs,
        func=lambda a: client.keyword_metrics(
            keywords=a.keywords,
            location_code=a.location_code,
            language_code=a.language_code,
        ),
    )

    tools: list[ValidatedTool] = [
        serp_organic_search,
        ai_overview_search,
        llm_visibility_lookup,
        keyword_metrics,
    ]
    return {tool.name: tool for tool in tools}


__all__ = ["build_dataforseo_tools"]
