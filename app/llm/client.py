"""OpenAI-backed LLM client + provider-selecting factory.

:class:`OpenAILLMClient` adapts LangChain's ``ChatOpenAI`` to the provider-neutral
:class:`~app.llm.base.LLMClient` interface:

- **Tool binding.** :class:`~app.llm.base.ToolSpec` objects are rendered to OpenAI
  function-tool definitions and bound so the *model* decides which tool to call and
  with what arguments (spec §3.3 / R7). Argument *validation* remains the job of
  :class:`~app.tools.base.ValidatedTool` before any real API call.
- **Token accounting.** Each response's ``usage_metadata`` is normalized into
  :class:`~app.llm.base.TokenUsage` and accumulated, surfacing ``total_tokens``
  (spec §4.2 / R32).
- **Resilience.** Calls run through the shared retry executor; transient LLM
  errors (rate limits, timeouts, connection/5xx) are retried with backoff+jitter,
  while deterministic errors (auth, bad request) fail fast — using the same
  retry/backoff machinery as the DataForSEO client (spec §3.5).

:func:`build_llm` returns the real client when configured, otherwise a
deterministic :class:`~app.llm.mock.ScriptedLLMClient`, so the pipeline runs with
zero credentials by default.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from app.config import Settings, get_settings
from app.llm.base import (
    LLMClient,
    LLMResponse,
    Message,
    TokenUsage,
    ToolCall,
    ToolSpec,
    UsageCallback,
)
from app.llm.mock import Responder, ScriptedLLMClient
from app.observability.logging import get_logger
from app.resilience.errors import ClassifiedError, NonRetryableError, RetryableError
from app.resilience.retry import RetryPolicy, retry_call

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import BaseMessage

_logger = get_logger("llm")

# Substrings of exception *type names* that indicate a transient LLM failure.
# Matching on names avoids a hard dependency on the openai SDK's exception types.
_RETRYABLE_ERROR_MARKERS: tuple[str, ...] = (
    "ratelimit",
    "timeout",
    "apiconnection",
    "connectionerror",
    "internalserver",
    "serviceunavailable",
    "serviceunavailableerror",
    "overloaded",
    "apierror",
)


def _classify_llm_error(exc: Exception) -> ClassifiedError:
    """Classify a provider exception as retryable (transient) or not.

    We inspect the exception's type name and any ``status_code`` attribute so this
    works across provider SDK versions without importing them.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status in (408, 409, 425, 429) or status >= 500:
            return ClassifiedError(
                code="llm_transient",
                retryable=True,
                message=f"retryable LLM error (HTTP {status})",
                status_code=status,
                detail={"exception": type(exc).__name__},
            )
        if status >= 400:
            return ClassifiedError(
                code="llm_client_error",
                retryable=False,
                message=f"non-retryable LLM error (HTTP {status})",
                status_code=status,
                detail={"exception": type(exc).__name__},
            )

    name = type(exc).__name__.lower()
    if any(marker in name for marker in _RETRYABLE_ERROR_MARKERS):
        return ClassifiedError(
            code="llm_transient",
            retryable=True,
            message="retryable LLM error",
            detail={"exception": type(exc).__name__},
        )

    return ClassifiedError(
        code="llm_error",
        retryable=False,
        message="non-retryable LLM error",
        detail={"exception": type(exc).__name__},
    )


class OpenAILLMClient(LLMClient):
    """Provider-neutral wrapper around LangChain's ``ChatOpenAI``."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        chat_model: BaseChatModel | None = None,
        retry_policy: RetryPolicy | None = None,
        on_usage: UsageCallback | None = None,
    ) -> None:
        super().__init__(on_usage=on_usage)
        self._settings = settings or get_settings()
        self._model_name = self._settings.llm_model
        self._chat = chat_model if chat_model is not None else self._build_chat_model()
        self._policy = retry_policy or RetryPolicy(
            max_attempts=self._settings.llm_max_retries,
            base_delay_s=self._settings.retry_base_delay_s,
            max_delay_s=self._settings.retry_max_delay_s,
        )

    def _build_chat_model(self) -> BaseChatModel:
        """Construct the real ``ChatOpenAI`` model (imported lazily)."""
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": self._settings.llm_model,
            "temperature": self._settings.llm_temperature,
            "timeout": self._settings.http_read_timeout_s,
            "max_retries": 0,  # our retry executor owns retries
        }
        if self._settings.openai_api_key:
            kwargs["api_key"] = self._settings.openai_api_key
        return ChatOpenAI(**kwargs)

    @property
    def model(self) -> str:
        return self._model_name

    def complete(
        self, messages: Sequence[Message], *, tools: Sequence[ToolSpec] | None = None
    ) -> LLMResponse:
        chat = self._bind_tools(tools)
        lc_messages = [_to_langchain_message(m) for m in messages]

        def operation() -> LLMResponse:
            try:
                ai_message = chat.invoke(lc_messages)
            except (RetryableError, NonRetryableError):
                raise
            except Exception as exc:  # normalize provider errors for the retry layer
                classified = _classify_llm_error(exc)
                if classified.retryable:
                    raise RetryableError(classified) from exc
                raise NonRetryableError(classified) from exc
            return _from_ai_message(ai_message, fallback_model=self._model_name)

        response = retry_call(operation, policy=self._policy)
        self._record_usage(response.usage)
        return response

    def _bind_tools(self, tools: Sequence[ToolSpec] | None) -> Any:
        """Bind tool definitions so the model can choose to call them."""
        if not tools:
            return self._chat
        openai_tools = [spec.to_openai_tool() for spec in tools]
        return self._chat.bind_tools(openai_tools)


def _to_langchain_message(message: Message) -> BaseMessage:
    """Convert an internal :class:`Message` to a LangChain message."""
    from langchain_core.messages import (
        AIMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )

    if message.role == "system":
        return SystemMessage(content=message.content)
    if message.role == "user":
        return HumanMessage(content=message.content)
    if message.role == "assistant":
        return AIMessage(content=message.content)
    # tool result message
    return ToolMessage(
        content=message.content,
        tool_call_id=message.tool_call_id or (message.name or "tool"),
    )


def _from_ai_message(ai_message: Any, *, fallback_model: str) -> LLMResponse:
    """Convert a LangChain ``AIMessage`` into an :class:`LLMResponse`."""
    tool_calls: list[ToolCall] = []
    for call in getattr(ai_message, "tool_calls", None) or []:
        # LangChain tool calls are dicts: {"name", "args", "id", "type"}.
        tool_calls.append(
            ToolCall(
                name=call.get("name", ""),
                args=dict(call.get("args") or {}),
                id=call.get("id"),
            )
        )

    usage = _extract_usage(ai_message)
    model = _extract_model(ai_message) or fallback_model
    content = ai_message.content if isinstance(ai_message.content, str) else str(ai_message.content)

    return LLMResponse(
        content=content,
        tool_calls=tuple(tool_calls),
        usage=usage,
        model=model,
    )


def _extract_usage(ai_message: Any) -> TokenUsage:
    """Pull token usage from ``usage_metadata`` (preferred) or response metadata."""
    usage_meta = getattr(ai_message, "usage_metadata", None)
    if isinstance(usage_meta, dict):
        return TokenUsage(
            input_tokens=int(usage_meta.get("input_tokens", 0) or 0),
            output_tokens=int(usage_meta.get("output_tokens", 0) or 0),
            total_tokens=int(usage_meta.get("total_tokens", 0) or 0),
        )

    response_meta = getattr(ai_message, "response_metadata", None)
    if isinstance(response_meta, dict):
        token_usage = response_meta.get("token_usage") or response_meta.get("usage")
        if isinstance(token_usage, dict):
            prompt = int(token_usage.get("prompt_tokens", 0) or 0)
            completion = int(token_usage.get("completion_tokens", 0) or 0)
            total = int(token_usage.get("total_tokens", prompt + completion) or 0)
            return TokenUsage(input_tokens=prompt, output_tokens=completion, total_tokens=total)

    return TokenUsage()


def _extract_model(ai_message: Any) -> str | None:
    """Best-effort extraction of the model name from response metadata."""
    response_meta = getattr(ai_message, "response_metadata", None)
    if isinstance(response_meta, dict):
        name = response_meta.get("model_name") or response_meta.get("model")
        if isinstance(name, str):
            return name
    return None


def build_llm(
    settings: Settings | None = None,
    *,
    on_usage: UsageCallback | None = None,
    responder: Responder | None = None,
    chat_model: BaseChatModel | None = None,
) -> LLMClient:
    """Build the configured LLM client.

    Returns an :class:`OpenAILLMClient` when ``settings.use_real_llm`` is true
    (``LLM_MODE=openai``, or ``auto`` with an API key present), otherwise a
    deterministic :class:`ScriptedLLMClient` so the pipeline runs with zero
    credentials. ``responder`` supplies deterministic behaviour for the mock path;
    ``chat_model`` injects a model (used by tests to avoid a real network call).
    """
    settings = settings or get_settings()

    if settings.use_real_llm or chat_model is not None:
        return OpenAILLMClient(settings=settings, chat_model=chat_model, on_usage=on_usage)

    _logger.info("llm.mock_mode", reason="no OPENAI_API_KEY / LLM_MODE=mock", model="mock-llm")
    return ScriptedLLMClient(responder=responder, on_usage=on_usage)


__all__ = ["OpenAILLMClient", "build_llm"]
