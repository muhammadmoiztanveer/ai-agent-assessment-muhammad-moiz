"""DataForSEO endpoint registry.

Each :class:`Endpoint` names one *logical* DataForSEO API call — its stable
internal name, the real HTTP method + path, and a short description. The client
has one method per endpoint, and the tool layer exposes one tool per endpoint,
so the "one tool = one logical API call" rule (spec §3.4) is structurally
enforced rather than left to convention.

The paths mirror real DataForSEO routes so the ``live`` client hits the right
URLs; in the default ``mock`` mode they simply act as fixture keys. All of these
endpoints use ``POST`` with a JSON array task body, which is DataForSEO's
convention for its ``/live/`` endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Endpoint:
    """A single logical DataForSEO API call."""

    name: str
    method: str
    path: str
    description: str


# --- SERP: organic Google results for a keyword ---------------------------- #
SERP_ORGANIC = Endpoint(
    name="serp_organic",
    method="POST",
    path="/v3/serp/google/organic/live/advanced",
    description="Live Google SERP organic results for a keyword.",
)

# --- SERP: Google AI Overview / AI Mode block for a keyword ---------------- #
AI_OVERVIEW = Endpoint(
    name="ai_overview",
    method="POST",
    path="/v3/serp/google/ai_mode/live/advanced",
    description="Google AI Overview / AI Mode answer block and cited sources for a keyword.",
)

# --- AI Optimization: brand visibility inside LLM answers ------------------ #
LLM_VISIBILITY = Endpoint(
    name="llm_visibility",
    method="POST",
    path="/v3/ai_optimization/llm_responses/live",
    description="Whether a brand/domain is cited in LLM assistant answers for a prompt.",
)

# --- DataForSEO Labs: search volume + keyword difficulty ------------------- #
KEYWORD_METRICS = Endpoint(
    name="keyword_metrics",
    method="POST",
    path="/v3/dataforseo_labs/google/keyword_overview/live",
    description="Search volume and competitive difficulty for one or more keywords.",
)


ALL_ENDPOINTS: tuple[Endpoint, ...] = (
    SERP_ORGANIC,
    AI_OVERVIEW,
    LLM_VISIBILITY,
    KEYWORD_METRICS,
)

# Lookup by stable internal name.
ENDPOINTS_BY_NAME: dict[str, Endpoint] = {e.name: e for e in ALL_ENDPOINTS}
