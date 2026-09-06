"""Extraction / Normalization agent — agent #3.

Its ONE job: turn the raw DataForSEO response envelopes gathered by the Retrieval
agent into clean, schema-conformant :class:`~app.agents.types.NormalizedQuery`
records. Parsing is purely deterministic and walks the standard
``tasks[].result[].items[]`` envelope, so it behaves identically for ``mock`` and
``live`` data.

For each keyword it merges signals from up to four endpoints:
- ``keyword_metrics`` → estimated search volume + competitive difficulty,
- ``serp_organic_search`` → whether the brand domain ranks organically (and where),
- ``ai_overview_search`` → whether the brand domain is cited in the AI Overview,
- ``llm_visibility_lookup`` → whether the brand is mentioned in LLM answers.

Atomicity guarantees (spec §3.2):
- Preserves factual values; never fabricates missing fields.
- Does NOT score opportunities, reason about strategy, call tools, or write prose.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.agents.types import NormalizedQuery, ProfileContext, normalize_domain
from app.db.models import VisibilityStatus
from app.observability.logging import get_logger
from app.tools.base import ToolResult

_logger = get_logger("agent.extraction")


@dataclass
class _Signal:
    """Mutable per-keyword accumulator merged into a NormalizedQuery at the end."""

    display: str
    volume: int | None = None
    difficulty: int | None = None
    serp_seen: bool = False
    serp_position: int | None = None
    ai_seen: bool = False
    ai_visible: bool = False
    llm_seen: bool = False
    llm_visible: bool = False
    sources: set[str] = field(default_factory=set)


def _iter_results(data: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield each ``result`` object from a DataForSEO envelope, defensively."""
    for task in data.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        for result in task.get("result") or []:
            if isinstance(result, dict):
                yield result


class ExtractionAgent:
    """Normalize raw tool results into clean per-keyword records."""

    def run(self, results: Sequence[ToolResult], profile: ProfileContext) -> list[NormalizedQuery]:
        """Parse successful tool results into normalized query records."""
        host = profile.host
        signals: dict[str, _Signal] = {}

        for result in results:
            if not result.ok or result.data is None:
                continue
            if result.tool == "keyword_metrics":
                self._ingest_keyword_metrics(result.data, signals)
            elif result.tool == "serp_organic_search":
                self._ingest_serp(result.data, host, signals)
            elif result.tool == "ai_overview_search":
                self._ingest_ai_overview(result.data, host, signals)
            elif result.tool == "llm_visibility_lookup":
                self._ingest_llm_visibility(result.data, signals)

        normalized = [self._to_normalized(signal) for signal in signals.values()]
        _logger.info("agent.extraction.done", extracted=len(normalized))
        return normalized

    # --- per-endpoint ingestion ------------------------------------------ #
    def _ingest_keyword_metrics(self, data: dict[str, Any], signals: dict[str, _Signal]) -> None:
        for result in _iter_results(data):
            for item in result.get("items") or []:
                keyword = item.get("keyword")
                if not isinstance(keyword, str) or not keyword.strip():
                    continue
                signal = self._signal_for(keyword, signals)
                info = item.get("keyword_info") or {}
                props = item.get("keyword_properties") or {}
                volume = info.get("search_volume")
                difficulty = props.get("keyword_difficulty")
                if isinstance(volume, int):
                    signal.volume = volume
                if isinstance(difficulty, int):
                    signal.difficulty = difficulty
                signal.sources.add("keyword_metrics")

    def _ingest_serp(self, data: dict[str, Any], host: str, signals: dict[str, _Signal]) -> None:
        for result in _iter_results(data):
            keyword = result.get("keyword")
            if not isinstance(keyword, str) or not keyword.strip():
                continue
            signal = self._signal_for(keyword, signals)
            signal.serp_seen = True
            signal.sources.add("serp_organic_search")
            for item in result.get("items") or []:
                if normalize_domain(str(item.get("domain", ""))) == host:
                    rank = item.get("rank_absolute")
                    position = rank if isinstance(rank, int) else None
                    # Keep the best (lowest) rank if the domain appears more than once.
                    if position is not None and (
                        signal.serp_position is None or position < signal.serp_position
                    ):
                        signal.serp_position = position

    def _ingest_ai_overview(
        self, data: dict[str, Any], host: str, signals: dict[str, _Signal]
    ) -> None:
        for result in _iter_results(data):
            keyword = result.get("keyword")
            if not isinstance(keyword, str) or not keyword.strip():
                continue
            signal = self._signal_for(keyword, signals)
            signal.ai_seen = True
            signal.sources.add("ai_overview_search")
            for block in result.get("items") or []:
                for reference in block.get("references") or []:
                    if normalize_domain(str(reference.get("domain", ""))) == host:
                        signal.ai_visible = True

    def _ingest_llm_visibility(self, data: dict[str, Any], signals: dict[str, _Signal]) -> None:
        for result in _iter_results(data):
            prompt = result.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                continue
            signal = self._signal_for(prompt, signals)
            signal.llm_seen = True
            signal.sources.add("llm_visibility_lookup")
            for response in result.get("responses") or []:
                if bool(response.get("brand_mentioned")):
                    signal.llm_visible = True

    # --- helpers --------------------------------------------------------- #
    @staticmethod
    def _signal_for(keyword: str, signals: dict[str, _Signal]) -> _Signal:
        """Fetch or create the accumulator for ``keyword`` (case-insensitive key)."""
        key = keyword.strip().lower()
        signal = signals.get(key)
        if signal is None:
            signal = _Signal(display=keyword.strip())
            signals[key] = signal
        return signal

    @staticmethod
    def _to_normalized(signal: _Signal) -> NormalizedQuery:
        """Collapse an accumulator into an immutable normalized record."""
        domain_visible = signal.serp_position is not None or signal.ai_visible or signal.llm_visible
        has_visibility_signal = signal.serp_seen or signal.ai_seen or signal.llm_seen
        if domain_visible:
            status = VisibilityStatus.VISIBLE
        elif has_visibility_signal:
            status = VisibilityStatus.NOT_VISIBLE
        else:
            status = VisibilityStatus.UNKNOWN

        return NormalizedQuery(
            query_text=signal.display,
            estimated_search_volume=signal.volume or 0,
            competitive_difficulty=signal.difficulty or 0,
            domain_visible=domain_visible,
            visibility_position=signal.serp_position,
            visibility_status=status,
            sources=tuple(sorted(signal.sources)),
        )


__all__ = ["ExtractionAgent"]
