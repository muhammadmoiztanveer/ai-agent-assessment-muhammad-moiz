"""Validating tool wrapper.

A :class:`ValidatedTool` binds a Pydantic argument schema to a callable and gives
the pipeline a single, safe entry point for tool execution:

1. **Validate first.** The LLM's proposed arguments are validated against the
   schema *before* the underlying function runs. Malformed or partial arguments
   never reach the real API — they come back as a clean, non-retryable
   ``ToolResult(ok=False, ...)`` instead of raising (spec §3.3, §3.8).
2. **Never crash the graph.** Any error from the underlying call is classified
   (retryable vs not) and returned inside a :class:`ToolResult`, so a node can
   inspect the outcome and route to a fallback rather than blowing up.
3. **Expose a JSON schema.** :meth:`ValidatedTool.json_schema` returns the tool's
   argument schema for binding to an LLM's tool-calling interface.

The wrapper is intentionally framework-neutral; the LLM layer adapts these into
provider/LangChain tool definitions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.resilience.errors import ClassifiedError, ResilienceError, classify

ArgsT = TypeVar("ArgsT", bound=BaseModel)


def _compact_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Reduce a Pydantic ValidationError to a small, JSON-safe list.

    We deliberately drop the raw input and URLs to keep the detail compact and
    free of any values the LLM may have hallucinated.
    """
    compact: list[dict[str, Any]] = []
    for err in exc.errors(include_url=False):
        compact.append(
            {
                "field": ".".join(str(p) for p in err.get("loc", ())) or "(root)",
                "type": err.get("type", "value_error"),
                "message": err.get("msg", "invalid value"),
            }
        )
    return compact


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Outcome of a tool invocation — success carries data, failure carries error."""

    ok: bool
    tool: str
    data: dict[str, Any] | None = None
    error: ClassifiedError | None = None
    args: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, tool: str, data: dict[str, Any], args: dict[str, Any]) -> ToolResult:
        return cls(ok=True, tool=tool, data=data, args=args)

    @classmethod
    def failure(
        cls, tool: str, error: ClassifiedError, args: dict[str, Any] | None = None
    ) -> ToolResult:
        return cls(ok=False, tool=tool, error=error, args=args or {})

    @property
    def retryable(self) -> bool:
        """Whether the failure (if any) is retryable. False for successes."""
        return bool(self.error and self.error.retryable)

    def as_dict(self) -> dict[str, Any]:
        """JSON-serializable representation for logs and state."""
        return {
            "ok": self.ok,
            "tool": self.tool,
            "args": self.args,
            "data": self.data,
            "error": self.error.as_dict() if self.error else None,
        }


class ValidatedTool(Generic[ArgsT]):
    """Bind an argument schema to a callable with validate-before-call semantics."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        args_schema: type[ArgsT],
        func: Callable[[ArgsT], dict[str, Any]],
    ) -> None:
        self.name = name
        self.description = description
        self.args_schema = args_schema
        self._func = func

    def json_schema(self) -> dict[str, Any]:
        """Return the JSON schema for this tool's arguments (for LLM binding)."""
        return self.args_schema.model_json_schema()

    def invoke(self, raw_args: Mapping[str, Any] | ArgsT) -> ToolResult:
        """Validate ``raw_args`` then run the tool, returning a :class:`ToolResult`.

        Never raises for expected failures: bad arguments become a non-retryable
        ``invalid_tool_args`` result, and downstream call errors are classified
        and returned. Only truly unexpected programming errors would propagate.
        """
        # 1) Validate arguments BEFORE touching the underlying call.
        try:
            args = (
                raw_args
                if isinstance(raw_args, self.args_schema)
                else self.args_schema.model_validate(dict(raw_args))
            )
        except ValidationError as exc:
            return ToolResult.failure(
                self.name,
                ClassifiedError(
                    code="invalid_tool_args",
                    retryable=False,
                    message=f"invalid arguments for tool '{self.name}'",
                    detail={"errors": _compact_validation_errors(exc)},
                ),
            )
        except (TypeError, ValueError) as exc:
            return ToolResult.failure(
                self.name,
                ClassifiedError(
                    code="invalid_tool_args",
                    retryable=False,
                    message=f"invalid arguments for tool '{self.name}'",
                    detail={"exception": type(exc).__name__},
                ),
            )

        args_dump = args.model_dump()

        # 2) Execute; classify any failure so the graph can route on it.
        try:
            data = self._func(args)
        except ResilienceError as exc:
            return ToolResult.failure(self.name, exc.classified, args_dump)
        except Exception as exc:  # deliberately convert any error into a result
            return ToolResult.failure(self.name, classify(exc), args_dump)

        return ToolResult.success(self.name, data, args_dump)


__all__ = ["ToolResult", "ValidatedTool"]
