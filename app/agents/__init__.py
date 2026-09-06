"""The five atomic agents: planner, retrieval, extraction, analysis, report.

Each agent has a single responsibility and communicates through the typed value
objects in :mod:`app.agents.types`. They are decoupled from the LangGraph state,
so they can be unit-tested in isolation and wired into the graph in Phase 7.
"""

from __future__ import annotations

from app.agents.analysis import AnalysisAgent, opportunity_score
from app.agents.extraction import ExtractionAgent
from app.agents.planner import PlannerAgent
from app.agents.report import ReportAgent
from app.agents.retrieval import RetrievalAgent
from app.agents.types import (
    AnalysisResult,
    Insight,
    NormalizedQuery,
    PlannedCall,
    ProfileContext,
    RecommendationDraft,
    Report,
    RetrievalOutcome,
    RetrievalPlan,
    normalize_domain,
)

__all__ = [
    "AnalysisAgent",
    "AnalysisResult",
    "ExtractionAgent",
    "Insight",
    "NormalizedQuery",
    "PlannedCall",
    "PlannerAgent",
    "ProfileContext",
    "RecommendationDraft",
    "Report",
    "ReportAgent",
    "RetrievalAgent",
    "RetrievalOutcome",
    "RetrievalPlan",
    "normalize_domain",
    "opportunity_score",
]
