"""Pydantic input schemas for each DataForSEO tool.

These models are the contract the LLM must satisfy when it decides to call a tool:
each field has an explicit type, a description (which the LLM reads to fill args
correctly), sane defaults, and validation bounds. The tool layer validates the
LLM's proposed arguments against these schemas *before* any real API call, so
malformed or partial arguments are rejected cleanly instead of reaching the
network (spec §3.3).

``location_code=2840`` is DataForSEO's code for the United States and
``language_code="en"`` for English — sensible defaults so the LLM can omit them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _StrictArgs(BaseModel):
    """Base for tool arg models: reject unknown fields, strip whitespace."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SerpOrganicSearchArgs(_StrictArgs):
    """Arguments for a Google organic SERP lookup."""

    keyword: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="The search query to fetch organic Google results for.",
    )
    location_code: int = Field(
        default=2840,
        ge=1,
        description="DataForSEO location code (2840 = United States).",
    )
    language_code: str = Field(
        default="en",
        min_length=2,
        max_length=10,
        description="Two-letter language code, e.g. 'en'.",
    )
    depth: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of organic results to retrieve (1-100).",
    )

    @field_validator("keyword")
    @classmethod
    def _keyword_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("keyword must not be blank")
        return value


class AiOverviewSearchArgs(_StrictArgs):
    """Arguments for a Google AI Overview / AI Mode lookup."""

    keyword: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="The query to fetch the Google AI Overview answer block for.",
    )
    location_code: int = Field(default=2840, ge=1, description="DataForSEO location code.")
    language_code: str = Field(
        default="en", min_length=2, max_length=10, description="Two-letter language code."
    )

    @field_validator("keyword")
    @classmethod
    def _keyword_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("keyword must not be blank")
        return value


class LlmVisibilityArgs(_StrictArgs):
    """Arguments for an LLM-answer brand-visibility lookup."""

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=400,
        description="The user-style prompt to test brand visibility against.",
    )
    brand: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="The brand or domain to check for citations in LLM answers.",
    )
    models: list[str] = Field(
        default_factory=lambda: ["gpt-4o", "gemini-1.5-pro", "perplexity"],
        max_length=10,
        description="LLM identifiers to query. Defaults to a representative set.",
    )

    @field_validator("models")
    @classmethod
    def _non_empty_models(cls, value: list[str]) -> list[str]:
        cleaned = [m.strip() for m in value if m and m.strip()]
        if not cleaned:
            raise ValueError("models must contain at least one non-empty model id")
        return cleaned


class KeywordMetricsArgs(_StrictArgs):
    """Arguments for a search-volume + keyword-difficulty lookup."""

    keywords: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="One or more keywords to fetch volume and difficulty for.",
    )
    location_code: int = Field(default=2840, ge=1, description="DataForSEO location code.")
    language_code: str = Field(
        default="en", min_length=2, max_length=10, description="Two-letter language code."
    )

    @field_validator("keywords")
    @classmethod
    def _clean_keywords(cls, value: list[str]) -> list[str]:
        cleaned = [k.strip() for k in value if k and k.strip()]
        if not cleaned:
            raise ValueError("keywords must contain at least one non-empty keyword")
        return cleaned


__all__ = [
    "AiOverviewSearchArgs",
    "KeywordMetricsArgs",
    "LlmVisibilityArgs",
    "SerpOrganicSearchArgs",
]
