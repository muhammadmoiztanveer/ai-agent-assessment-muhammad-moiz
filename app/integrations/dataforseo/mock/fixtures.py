"""Deterministic mock fixtures modeled on real DataForSEO response envelopes.

These builders produce responses that are byte-for-byte reproducible for a given
input (seeded by the keyword), so tests are hermetic and a live demo is stable
without any credentials or network. The envelope shape mirrors DataForSEO's real
contract:

    {
      "version": "...", "status_code": 20000, "status_message": "Ok.",
      "cost": 0.0, "tasks_count": 1, "tasks_error": 0,
      "tasks": [
        {"id": "...", "status_code": 20000, "result_count": 1,
         "result": [ { ...endpoint-specific payload... } ]}
      ]
    }

The extraction agent (a later phase) parses ``tasks[].result[]`` identically
whether the data came from ``mock`` or ``live`` mode, so extraction logic never
branches on the source.
"""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime, timedelta
from typing import Any

_VERSION = "0.1.20240101"

# A fixed reference time so mock timestamps are realistic yet fully deterministic
# (a mock must be byte-for-byte reproducible; wall-clock ``now()`` would not be).
_BASE_TIME = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
_STATUS_OK = 20000
_STATUS_MESSAGE_OK = "Ok."

# A deterministic pool of competitor/reference domains the mock SERP draws from.
_DOMAIN_POOL: tuple[str, ...] = (
    "wikipedia.org",
    "hubspot.com",
    "moz.com",
    "semrush.com",
    "ahrefs.com",
    "backlinko.com",
    "searchenginejournal.com",
    "neilpatel.com",
    "surferseo.com",
    "reddit.com",
    "medium.com",
    "forbes.com",
)


def _seed_for(text: str) -> random.Random:
    """A stable RNG seeded by ``text`` so fixtures are reproducible."""
    digest = hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _task_id(rng: random.Random) -> str:
    """A DataForSEO-style task id."""
    return f"{rng.randint(10**14, 10**15 - 1)}-1-0-0"


def _mock_datetime(rng: random.Random) -> str:
    """A deterministic ISO timestamp derived from the seeded RNG."""
    return (_BASE_TIME - timedelta(seconds=rng.randint(0, 86_400))).isoformat()


def _envelope(task_id: str, result: list[dict[str, Any]], *, cost: float = 0.01) -> dict[str, Any]:
    """Wrap an endpoint-specific result list in the standard DataForSEO envelope."""
    return {
        "version": _VERSION,
        "status_code": _STATUS_OK,
        "status_message": _STATUS_MESSAGE_OK,
        "time": "0.0123 sec.",
        "cost": cost,
        "tasks_count": 1,
        "tasks_error": 0,
        "tasks": [
            {
                "id": task_id,
                "status_code": _STATUS_OK,
                "status_message": _STATUS_MESSAGE_OK,
                "time": "0.0100 sec.",
                "cost": cost,
                "result_count": len(result),
                "path": ["v3"],
                "result": result,
            }
        ],
    }


# --------------------------------------------------------------------------- #
# SERP organic
# --------------------------------------------------------------------------- #
def serp_organic(keyword: str, *, location_code: int, language_code: str, depth: int) -> dict:
    """Build a mock Google organic SERP response for ``keyword``."""
    rng = _seed_for(keyword)
    count = max(1, min(depth, 10))
    domains = rng.sample(_DOMAIN_POOL, k=min(count, len(_DOMAIN_POOL)))
    slug = keyword.strip().lower().replace(" ", "-")

    items: list[dict[str, Any]] = []
    for rank, domain in enumerate(domains, start=1):
        items.append(
            {
                "type": "organic",
                "rank_group": rank,
                "rank_absolute": rank,
                "domain": domain,
                "title": f"{keyword.title()} — Guide by {domain.split('.')[0].title()}",
                "url": f"https://{domain}/{slug}",
                "description": f"Everything about {keyword} explained by {domain}.",
                "breadcrumb": f"https://{domain} > {slug}",
            }
        )

    result = [
        {
            "keyword": keyword,
            "type": "organic",
            "se_domain": "google.com",
            "location_code": location_code,
            "language_code": language_code,
            "check_url": (
                f"https://www.google.com/search?q={keyword.replace(' ', '+')}"
                f"&num={count}&hl={language_code}"
            ),
            "datetime": _mock_datetime(rng),
            "item_types": ["organic"],
            "se_results_count": rng.randint(100_000, 90_000_000),
            "items_count": len(items),
            "items": items,
        }
    ]
    return _envelope(_task_id(rng), result)


# --------------------------------------------------------------------------- #
# AI Overview / AI Mode
# --------------------------------------------------------------------------- #
def ai_overview(keyword: str, *, location_code: int, language_code: str) -> dict:
    """Build a mock Google AI Overview response with an answer + cited sources."""
    rng = _seed_for(f"ai::{keyword}")
    reference_domains = rng.sample(_DOMAIN_POOL, k=rng.randint(2, 4))
    references = [
        {
            "type": "ai_overview_reference",
            "rank_absolute": i,
            "domain": domain,
            "title": f"{keyword.title()} overview — {domain.split('.')[0].title()}",
            "url": f"https://{domain}/{keyword.strip().lower().replace(' ', '-')}",
        }
        for i, domain in enumerate(reference_domains, start=1)
    ]
    result = [
        {
            "keyword": keyword,
            "type": "ai_mode",
            "se_domain": "google.com",
            "location_code": location_code,
            "language_code": language_code,
            "datetime": _mock_datetime(rng),
            "items": [
                {
                    "type": "ai_overview",
                    "markdown": (
                        f"When evaluating **{keyword}**, buyers usually compare features, "
                        f"pricing, and integrations. Leading resources cover setup, best "
                        f"practices, and comparisons."
                    ),
                    "references": references,
                }
            ],
        }
    ]
    return _envelope(_task_id(rng), result, cost=0.02)


# --------------------------------------------------------------------------- #
# LLM visibility (AI Optimization)
# --------------------------------------------------------------------------- #
def llm_visibility(prompt: str, *, brand: str, models: list[str]) -> dict:
    """Build a mock LLM-answer visibility response for a brand across models."""
    rng = _seed_for(f"llm::{brand}::{prompt}")
    responses = []
    for model in models:
        mentioned = rng.random() > 0.5
        cited = rng.sample(_DOMAIN_POOL, k=rng.randint(1, 3))
        responses.append(
            {
                "model": model,
                "prompt": prompt,
                "brand": brand,
                "brand_mentioned": mentioned,
                "mention_rank": rng.randint(1, 5) if mentioned else None,
                "cited_domains": cited,
                "answer_excerpt": (
                    f"For '{prompt}', notable options include several established tools"
                    + (f", such as {brand}." if mentioned else ".")
                ),
            }
        )
    result = [
        {
            "prompt": prompt,
            "brand": brand,
            "models_count": len(models),
            "responses": responses,
        }
    ]
    return _envelope(_task_id(rng), result, cost=0.05)


# --------------------------------------------------------------------------- #
# Keyword metrics (search volume + difficulty)
# --------------------------------------------------------------------------- #
def keyword_metrics(keywords: list[str], *, location_code: int, language_code: str) -> dict:
    """Build a mock search-volume + keyword-difficulty response for keywords."""
    items: list[dict[str, Any]] = []
    for keyword in keywords:
        rng = _seed_for(f"kw::{keyword}")
        volume = rng.randint(80, 22_000)
        difficulty = rng.randint(3, 96)
        competition = round(rng.uniform(0.05, 0.98), 2)
        items.append(
            {
                "keyword": keyword,
                "location_code": location_code,
                "language_code": language_code,
                "keyword_info": {
                    "search_volume": volume,
                    "competition": competition,
                    "competition_level": (
                        "LOW" if competition < 0.34 else "MEDIUM" if competition < 0.67 else "HIGH"
                    ),
                    "cpc": round(rng.uniform(0.2, 12.0), 2),
                },
                "keyword_properties": {
                    "keyword_difficulty": difficulty,
                },
            }
        )
    result = [
        {
            "location_code": location_code,
            "language_code": language_code,
            "items_count": len(items),
            "items": items,
        }
    ]
    return _envelope(_task_id(_seed_for("".join(keywords))), result)
