"""Provider-neutral LLM abstraction.

This module defines the small, framework-independent vocabulary the rest of the
system speaks to a language model, so agents never import a provider SDK directly:

- :class:`Message` — a single chat turn (system / user / assistant / tool).
- :class:`ToolSpec` — a tool advertised to the model (name, description, JSON
  argument schema). Built from a :class:`~app.tools.base.ValidatedTool`.
- :class:`ToolCall` — the model's decision to call a tool with specific args.
- :class:`TokenUsage` — token accounting for one completion (spec §4.2 / R32).
- :class:`LLMResponse` — the normalized result of one completion.
- :class:`LLMClient` — the abstract client; concrete implementations are the real
  OpenAI-backed client and a deterministic scripted client for tests / keyless runs.

Keeping this layer provider-neutral means the DAG and agents are decoupled from
whichever model backs them, and testing needs no network or API key.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from app.tools.base import ValidatedTool

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class Message:
    """A single chat message.

    ``name``/``tool_call_id`` are only meaningful for ``tool`` messages, which
    carry the result of a tool call back to the model.
    """

    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None

    @classmethod
    def system(cls, content: str) -> Message:
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> Message:
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str) -> Message:
        return cls(role="assistant", content=content)

    @classmethod
    def tool(cls, content: str, *, name: str, tool_call_id: str | None = None) -> Message:
        return cls(role="tool", content=content, name=name, tool_call_id=tool_call_id)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool advertised to the model: name, description, and JSON arg schema."""

    name: str
    description: str
    parameters: dict[str, Any]

    @classmethod
    def from_validated_tool(cls, tool: ValidatedTool) -> ToolSpec:
        """Derive a :class:`ToolSpec` from a :class:`ValidatedTool`."""
        return cls(
            name=tool.name,
            description=tool.description,
            parameters=tool.json_schema(),
        )

    def to_openai_tool(self) -> dict[str, Any]:
        """Render as an OpenAI-style function-tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A model-requested tool invocation."""

    name: str
    args: dict[str, Any]
    id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "args": self.args}


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token accounting for a single completion.

    Providers may not always report usage; unknown values default to ``0`` so the
    accumulated total is always a well-defined integer (spec: surface tokens
    "if the provider gives it").
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_counts(cls, input_tokens: int, output_tokens: int) -> TokenUsage:
        """Build usage from prompt/completion counts, deriving the total."""
        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Normalized result of a single completion."""

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """The inputs to one completion — handed to a scripted responder for tests."""

    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()

    @property
    def last_user_message(self) -> Message | None:
        for message in reversed(self.messages):
            if message.role == "user":
                return message
        return None


UsageCallback = Callable[[TokenUsage], None]


class LLMClient(ABC):
    """Abstract chat client with built-in token accounting.

    Concrete subclasses implement :meth:`complete`; the base class accumulates
    token usage across calls and forwards each completion's usage to an optional
    callback (used to feed the per-run metrics collector, R18/R32).
    """

    def __init__(self, *, on_usage: UsageCallback | None = None) -> None:
        self._on_usage = on_usage
        self._total_usage = TokenUsage()

    @property
    @abstractmethod
    def model(self) -> str:
        """Identifier of the underlying model."""

    @property
    def total_usage(self) -> TokenUsage:
        """Cumulative token usage across every completion made by this client."""
        return self._total_usage

    @property
    def total_tokens(self) -> int:
        """Cumulative total tokens across every completion (spec §4.2 / R32)."""
        return self._total_usage.total_tokens

    def _record_usage(self, usage: TokenUsage) -> None:
        """Accumulate usage and notify the callback. Call from :meth:`complete`."""
        self._total_usage = self._total_usage + usage
        if self._on_usage is not None:
            self._on_usage(usage)

    @abstractmethod
    def complete(
        self, messages: Sequence[Message], *, tools: Sequence[ToolSpec] | None = None
    ) -> LLMResponse:
        """Run one completion over ``messages``, optionally offering ``tools``."""


def specs_from_tools(tools: Sequence[ValidatedTool]) -> list[ToolSpec]:
    """Convenience: build :class:`ToolSpec` list from validated tools."""
    return [ToolSpec.from_validated_tool(tool) for tool in tools]


__all__ = [
    "LLMClient",
    "LLMRequest",
    "LLMResponse",
    "Message",
    "Role",
    "TokenUsage",
    "ToolCall",
    "ToolSpec",
    "UsageCallback",
    "specs_from_tools",
]
