"""Search / Retrieval agent — agent #2.

Its ONE job: execute the planned tool calls. For each
:class:`~app.agents.types.PlannedCall` it looks up the matching
:class:`~app.tools.base.ValidatedTool` and invokes it. The tool validates the
arguments *before* the real API call and returns a
:class:`~app.tools.base.ToolResult` (never raising), so the retrieval agent turns
a plan into a :class:`~app.agents.types.RetrievalOutcome` of raw results plus
classified errors — collecting failures instead of crashing (spec §3.3, §3.5).

Atomicity guarantees (spec §3.2):
- Does NOT normalize, interpret, score, or summarize results.
- Does NOT decide *what* to fetch — that was the Planner's job.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.agents.types import RetrievalOutcome, RetrievalPlan
from app.observability.logging import get_logger
from app.resilience.errors import ClassifiedError
from app.tools.base import ToolResult, ValidatedTool

_logger = get_logger("agent.retrieval")


class RetrievalAgent:
    """Execute a retrieval plan against the validated DataForSEO tools."""

    def __init__(self, *, tools: Mapping[str, ValidatedTool]) -> None:
        self._tools = dict(tools)

    def run(self, plan: RetrievalPlan) -> RetrievalOutcome:
        """Invoke every planned call, gathering raw results and classified errors."""
        results: list[ToolResult] = []
        errors: list[ClassifiedError] = []

        for call in plan.calls:
            tool = self._tools.get(call.tool)
            if tool is None:
                error = ClassifiedError(
                    code="unknown_tool",
                    retryable=False,
                    message=f"no tool registered for '{call.tool}'",
                    detail={"tool": call.tool},
                )
                results.append(ToolResult.failure(call.tool, error, call.args))
                errors.append(error)
                continue

            result = tool.invoke(call.args)
            results.append(result)
            if not result.ok and result.error is not None:
                errors.append(result.error)

        _logger.info(
            "agent.retrieval.done",
            planned=plan.call_count,
            succeeded=sum(1 for r in results if r.ok),
            failed=len(errors),
        )
        return RetrievalOutcome(results=tuple(results), errors=tuple(errors))


__all__ = ["RetrievalAgent"]
