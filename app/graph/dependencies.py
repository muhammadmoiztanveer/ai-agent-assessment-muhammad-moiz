"""Dependency wiring for the pipeline graph.

:class:`PipelineDependencies` bundles the five agents plus the LLM client the
graph nodes need. It is built once per run by :func:`build_dependencies`, which
constructs the DataForSEO client, the validated tool registry, the LLM client,
and the agents in the correct order.

Building per run matters for two reasons:

- **Token accounting (R32).** The LLM client accumulates ``total_tokens`` over its
  lifetime; a fresh client per run means ``total_tokens`` reflects exactly that
  run. When a per-run metrics collector is supplied, the client's usage callback
  feeds it directly.
- **Isolation.** A run gets its own DataForSEO client (and therefore its own
  circuit-breaker state), so one run's failures never leak into another's.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.analysis import AnalysisAgent
from app.agents.extraction import ExtractionAgent
from app.agents.planner import PlannerAgent
from app.agents.report import ReportAgent
from app.agents.retrieval import RetrievalAgent
from app.config import Settings, get_settings
from app.integrations.dataforseo.client import DataForSeoClient, build_client
from app.llm.base import LLMClient, TokenUsage, UsageCallback
from app.llm.client import build_llm
from app.observability.metrics import RunMetrics
from app.tools.base import ValidatedTool
from app.tools.dataforseo_tools import build_dataforseo_tools


@dataclass(slots=True)
class PipelineDependencies:
    """The agents and LLM client a single pipeline run executes against."""

    settings: Settings
    llm: LLMClient
    tools: dict[str, ValidatedTool]
    planner: PlannerAgent
    retrieval: RetrievalAgent
    extraction: ExtractionAgent
    analysis: AnalysisAgent
    report: ReportAgent

    @property
    def total_tokens(self) -> int:
        """Cumulative LLM tokens used so far by this run's client (spec §4.2)."""
        return self.llm.total_tokens


def build_dependencies(
    settings: Settings | None = None,
    *,
    metrics: RunMetrics | None = None,
    client: DataForSeoClient | None = None,
    llm: LLMClient | None = None,
) -> PipelineDependencies:
    """Construct the full set of dependencies for one pipeline run.

    Args:
        settings: Configuration (defaults to the cached process settings).
        metrics: When provided, the LLM client reports per-completion usage into
            it so the run's metrics carry an accurate token total.
        client: Inject a pre-built DataForSEO client (tests / recheck reuse).
        llm: Inject a pre-built LLM client (tests). When omitted, the client is
            built from settings — a real OpenAI client if configured, otherwise a
            deterministic keyless client.
    """
    settings = settings or get_settings()
    if client is None:
        # Wire the client's retry callback into the run metrics so retries are
        # counted and attributed to the node during which they occur.
        on_retry = (lambda _attempt: metrics.record_retry()) if metrics is not None else None
        client = build_client(settings, on_retry=on_retry)
    tools = build_dataforseo_tools(client)

    if llm is None:
        on_usage: UsageCallback | None = None
        if metrics is not None:
            # Adapt the per-completion TokenUsage callback onto the metrics
            # collector's token counter (keeps observability decoupled from the
            # LLM types — the graph owns the wiring).
            def on_usage(usage: TokenUsage) -> None:
                metrics.add_tokens(usage.total_tokens)

        llm = build_llm(settings, on_usage=on_usage)

    return PipelineDependencies(
        settings=settings,
        llm=llm,
        tools=tools,
        planner=PlannerAgent(llm=llm, tools=tools),
        retrieval=RetrievalAgent(tools=tools),
        extraction=ExtractionAgent(),
        analysis=AnalysisAgent(settings=settings, llm=llm),
        report=ReportAgent(llm=llm),
    )


__all__ = ["PipelineDependencies", "build_dependencies"]
