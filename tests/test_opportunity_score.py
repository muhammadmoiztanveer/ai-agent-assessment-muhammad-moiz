"""Mandated coverage — the opportunity_score formula (spec §4.2 / R31).

``opportunity_score`` is the one number the whole product is ranked by, so it is
tested directly: exact values for known inputs, hard bounds of ``[0, 1]`` under
extreme/degenerate inputs, monotonicity in each of its three signals, sensitivity
to configured weights, and the downstream ranking behaviour of the Analysis agent.
"""

from __future__ import annotations

import math

from app.agents.analysis import AnalysisAgent, opportunity_score
from app.agents.types import NormalizedQuery, ProfileContext
from app.config import Settings
from app.db.models import VisibilityStatus
from app.llm.mock import ScriptedLLMClient


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Exact formula
# --------------------------------------------------------------------------- #
def test_known_value_not_visible() -> None:
    # volume_norm=0.5, difficulty_ease=0.6, gap=1.0
    # 0.4*0.5 + 0.3*0.6 + 0.3*1.0 = 0.2 + 0.18 + 0.30 = 0.68
    score = opportunity_score(
        estimated_search_volume=5_000,
        competitive_difficulty=40,
        domain_visible=False,
        settings=_settings(),
    )
    assert score == 0.68


def test_known_value_visible_drops_the_gap_term() -> None:
    # Same inputs but visible → gap term (0.3) removed → 0.38
    score = opportunity_score(
        estimated_search_volume=5_000,
        competitive_difficulty=40,
        domain_visible=True,
        settings=_settings(),
    )
    assert score == 0.38


# --------------------------------------------------------------------------- #
# Bounds: always within [0, 1]
# --------------------------------------------------------------------------- #
def test_maximum_case_is_one() -> None:
    score = opportunity_score(
        estimated_search_volume=1_000_000,  # far above the cap → volume_norm=1
        competitive_difficulty=0,  # ease=1
        domain_visible=False,  # gap=1
        settings=_settings(),
    )
    assert score == 1.0


def test_minimum_case_is_zero() -> None:
    score = opportunity_score(
        estimated_search_volume=0,
        competitive_difficulty=100,
        domain_visible=True,
        settings=_settings(),
    )
    assert score == 0.0


def test_degenerate_inputs_are_clamped_into_bounds() -> None:
    # Negative volume and out-of-range difficulty must not escape [0, 1].
    score = opportunity_score(
        estimated_search_volume=-500,
        competitive_difficulty=250,
        domain_visible=False,
        settings=_settings(),
    )
    assert 0.0 <= score <= 1.0
    # volume_norm=0, ease=0 (clamped), gap=1 → 0.3
    assert score == 0.3


# --------------------------------------------------------------------------- #
# Monotonicity in each signal
# --------------------------------------------------------------------------- #
def test_higher_volume_scores_higher() -> None:
    s = _settings()
    low = opportunity_score(
        estimated_search_volume=1_000,
        competitive_difficulty=50,
        domain_visible=False,
        settings=s,
    )
    high = opportunity_score(
        estimated_search_volume=9_000,
        competitive_difficulty=50,
        domain_visible=False,
        settings=s,
    )
    assert high > low


def test_lower_difficulty_scores_higher() -> None:
    s = _settings()
    hard = opportunity_score(
        estimated_search_volume=5_000,
        competitive_difficulty=90,
        domain_visible=False,
        settings=s,
    )
    easy = opportunity_score(
        estimated_search_volume=5_000,
        competitive_difficulty=10,
        domain_visible=False,
        settings=s,
    )
    assert easy > hard


def test_visibility_gap_increases_score() -> None:
    s = _settings()
    visible = opportunity_score(
        estimated_search_volume=5_000,
        competitive_difficulty=50,
        domain_visible=True,
        settings=s,
    )
    missing = opportunity_score(
        estimated_search_volume=5_000,
        competitive_difficulty=50,
        domain_visible=False,
        settings=s,
    )
    assert missing > visible


# --------------------------------------------------------------------------- #
# Configurable weights
# --------------------------------------------------------------------------- #
def test_custom_weights_change_the_result() -> None:
    # All weight on the visibility gap → score equals the gap term exactly.
    gap_only = _settings(
        OPP_WEIGHT_VOLUME=0.0,
        OPP_WEIGHT_DIFFICULTY=0.0,
        OPP_WEIGHT_GAP=1.0,
    )
    assert (
        opportunity_score(
            estimated_search_volume=5_000,
            competitive_difficulty=40,
            domain_visible=False,
            settings=gap_only,
        )
        == 1.0
    )
    assert (
        opportunity_score(
            estimated_search_volume=5_000,
            competitive_difficulty=40,
            domain_visible=True,
            settings=gap_only,
        )
        == 0.0
    )


def test_result_is_rounded_to_four_decimals() -> None:
    score = opportunity_score(
        estimated_search_volume=3_333,
        competitive_difficulty=37,
        domain_visible=False,
        settings=_settings(),
    )
    # Rounded to 4 dp: the decimal component has at most four digits.
    assert round(score, 4) == score
    assert math.isclose(score, round(score, 4))


# --------------------------------------------------------------------------- #
# Downstream ranking by the Analysis agent
# --------------------------------------------------------------------------- #
def test_analysis_agent_ranks_insights_by_score_desc() -> None:
    records = [
        NormalizedQuery(
            query_text="low value",
            estimated_search_volume=100,
            competitive_difficulty=90,
            domain_visible=True,
            visibility_position=1,
            visibility_status=VisibilityStatus.VISIBLE,
            sources=("serp_organic_search",),
        ),
        NormalizedQuery(
            query_text="high value gap",
            estimated_search_volume=9_500,
            competitive_difficulty=15,
            domain_visible=False,
            visibility_position=None,
            visibility_status=VisibilityStatus.NOT_VISIBLE,
            sources=("keyword_metrics",),
        ),
    ]
    profile = ProfileContext(name="Acme", domain="acme.com", industry="SaaS", competitors=())
    agent = AnalysisAgent(settings=_settings(), llm=ScriptedLLMClient())

    result = agent.run(records, profile)
    scores = [i.opportunity_score for i in result.insights]

    assert scores == sorted(scores, reverse=True)
    assert result.insights[0].query_text == "high value gap"
    assert all(0.0 <= i.opportunity_score <= 1.0 for i in result.insights)
