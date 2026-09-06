"""Deterministic, provider-free LLM client.

:class:`ScriptedLLMClient` implements :class:`~app.llm.base.LLMClient` without any
network or API key. It serves two purposes:

1. **Hermetic tests.** Configure it with an ordered list of canned
   :class:`~app.llm.base.LLMResponse` objects (consumed one per :meth:`complete`
   call) *or* a ``responder`` callable that maps an
   :class:`~app.llm.base.LLMRequest` to a response. Tests get fully deterministic,
   assertable model behaviour — including scripted tool calls.
2. **Keyless runtime.** When no ``OPENAI_API_KEY`` is configured, the factory
   falls back to this client so the whole pipeline still runs end-to-end (mirroring
   the DataForSEO ``mock`` philosophy). Agents inject their own deterministic
   ``responder`` in that mode.

Token usage is still accounted for: each canned response's usage is recorded, so
``total_tokens`` behaves identically to the real client.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence

from app.llm.base import (
    LLMClient,
    LLMRequest,
    LLMResponse,
    Message,
    ToolSpec,
    UsageCallback,
)

Responder = Callable[[LLMRequest], LLMResponse]


class ScriptedLLMClient(LLMClient):
    """A deterministic client driven by canned responses or a responder callable."""

    def __init__(
        self,
        responses: Sequence[LLMResponse] | None = None,
        *,
        responder: Responder | None = None,
        default: LLMResponse | None = None,
        model: str = "mock-llm",
        on_usage: UsageCallback | None = None,
    ) -> None:
        """Configure the client.

        Args:
            responses: Ordered responses returned one per call. Takes precedence
                over ``responder`` while any remain.
            responder: Callable invoked with the :class:`LLMRequest` when the
                scripted ``responses`` are exhausted (or none were given).
            default: Response used when neither a scripted response nor a responder
                is available. Defaults to an empty assistant message.
            model: Reported model identifier.
            on_usage: Optional per-completion usage callback.
        """
        super().__init__(on_usage=on_usage)
        self._queue: deque[LLMResponse] = deque(responses or ())
        self._responder = responder
        self._default = default if default is not None else LLMResponse(content="")
        self._model = model
        self.call_count = 0

    @property
    def model(self) -> str:
        return self._model

    @property
    def remaining(self) -> int:
        """How many scripted responses are still queued."""
        return len(self._queue)

    def complete(
        self, messages: Sequence[Message], *, tools: Sequence[ToolSpec] | None = None
    ) -> LLMResponse:
        self.call_count += 1
        request = LLMRequest(messages=tuple(messages), tools=tuple(tools or ()))

        if self._queue:
            response = self._queue.popleft()
        elif self._responder is not None:
            response = self._responder(request)
        else:
            response = self._default

        # Stamp the model name when the scripted response didn't set one.
        if response.model is None:
            response = LLMResponse(
                content=response.content,
                tool_calls=response.tool_calls,
                usage=response.usage,
                model=self._model,
            )

        self._record_usage(response.usage)
        return response


__all__ = ["Responder", "ScriptedLLMClient"]
