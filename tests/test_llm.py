"""Phase 5 tests: the LLM layer.

Covers the four things the LLM layer is responsible for:
  1. provider-neutral types + tool binding (ToolSpec from ValidatedTool, OpenAI
     function-tool rendering),
  2. token accounting across completions (R32),
  3. the deterministic scripted client (hermetic tests + keyless runtime),
  4. the OpenAI client's message/tool-call/usage extraction and resilient retry
     behaviour, exercised through an injected fake chat model (no network, no key).

All tests are hermetic and require no API key.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from app.config import Settings
from app.integrations.dataforseo.client import DataForSeoClient
from app.llm.base import (
    LLMRequest,
    LLMResponse,
    Message,
    TokenUsage,
    ToolCall,
    specs_from_tools,
)
from app.llm.client import OpenAILLMClient, build_llm
from app.llm.mock import ScriptedLLMClient
from app.llm.prompts import AGENT_PROMPTS, PROMPT_VERSION, get_prompt
from app.resilience.retry import RetryPolicy
from app.tools.dataforseo_tools import build_dataforseo_tools

_FAST = RetryPolicy(max_attempts=3, base_delay_s=0.0, max_delay_s=0.0, jitter=False)


# --------------------------------------------------------------------------- #
# Message + TokenUsage value types
# --------------------------------------------------------------------------- #
def test_message_constructors_set_roles() -> None:
    assert Message.system("s").role == "system"
    assert Message.user("u").role == "user"
    assert Message.assistant("a").role == "assistant"
    tool = Message.tool("result", name="serp", tool_call_id="call_1")
    assert tool.role == "tool"
    assert tool.name == "serp"
    assert tool.tool_call_id == "call_1"


def test_token_usage_addition_and_from_counts() -> None:
    a = TokenUsage.from_counts(10, 5)
    assert a.total_tokens == 15
    combined = a + TokenUsage.from_counts(1, 2)
    assert combined.input_tokens == 11
    assert combined.output_tokens == 7
    assert combined.total_tokens == 18
    assert combined.as_dict() == {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}


# --------------------------------------------------------------------------- #
# Tool binding: ValidatedTool -> ToolSpec -> OpenAI function tool
# --------------------------------------------------------------------------- #
def test_tool_spec_from_validated_tool_and_openai_rendering() -> None:
    tools = build_dataforseo_tools(DataForSeoClient(retry_policy=_FAST))
    specs = specs_from_tools(list(tools.values()))
    assert {s.name for s in specs} == set(tools)

    serp = next(s for s in specs if s.name == "serp_organic_search")
    assert serp.description  # non-empty description guides the model
    assert serp.parameters["type"] == "object"
    assert "keyword" in serp.parameters["properties"]

    openai_tool = serp.to_openai_tool()
    assert openai_tool["type"] == "function"
    assert openai_tool["function"]["name"] == "serp_organic_search"
    assert openai_tool["function"]["parameters"]["type"] == "object"


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
def test_all_five_agent_prompts_present_and_versioned() -> None:
    assert set(AGENT_PROMPTS) == {"planner", "retrieval", "extraction", "analysis", "report"}
    assert PROMPT_VERSION
    for name in AGENT_PROMPTS:
        assert get_prompt(name).strip()


def test_get_prompt_unknown_agent_raises() -> None:
    with pytest.raises(KeyError):
        get_prompt("nonexistent")


# --------------------------------------------------------------------------- #
# ScriptedLLMClient: canned responses, responder, default, token accounting
# --------------------------------------------------------------------------- #
def test_scripted_client_returns_queued_responses_in_order() -> None:
    client = ScriptedLLMClient(
        [
            LLMResponse(content="first", usage=TokenUsage.from_counts(3, 2)),
            LLMResponse(content="second", usage=TokenUsage.from_counts(1, 1)),
        ]
    )
    assert client.remaining == 2
    first = client.complete([Message.user("hi")])
    second = client.complete([Message.user("again")])

    assert first.content == "first"
    assert second.content == "second"
    assert client.call_count == 2
    # Tokens accumulate across both completions.
    assert client.total_tokens == 7
    assert client.total_usage.input_tokens == 4


def test_scripted_client_falls_back_to_responder_when_queue_empty() -> None:
    def responder(request: LLMRequest) -> LLMResponse:
        last = request.last_user_message
        return LLMResponse(content=f"echo:{last.content if last else ''}")

    client = ScriptedLLMClient(responder=responder)
    result = client.complete([Message.system("sys"), Message.user("ping")])
    assert result.content == "echo:ping"
    # The mock stamps its model name onto responses that don't set one.
    assert result.model == "mock-llm"


def test_scripted_client_default_response_when_nothing_configured() -> None:
    client = ScriptedLLMClient()
    result = client.complete([Message.user("hi")])
    assert result.content == ""
    assert result.has_tool_calls is False


def test_scripted_client_can_script_tool_calls() -> None:
    scripted = LLMResponse(
        content="",
        tool_calls=(ToolCall(name="serp_organic_search", args={"keyword": "crm"}, id="c1"),),
    )
    client = ScriptedLLMClient([scripted])
    result = client.complete([Message.user("plan")], tools=[])
    assert result.has_tool_calls is True
    assert result.tool_calls[0].name == "serp_organic_search"
    assert result.tool_calls[0].args == {"keyword": "crm"}


def test_scripted_client_forwards_usage_to_callback() -> None:
    seen: list[int] = []
    client = ScriptedLLMClient(
        [LLMResponse(content="x", usage=TokenUsage.from_counts(5, 5))],
        on_usage=lambda u: seen.append(u.total_tokens),
    )
    client.complete([Message.user("hi")])
    assert seen == [10]


# --------------------------------------------------------------------------- #
# OpenAILLMClient via an injected fake chat model (no network / key)
# --------------------------------------------------------------------------- #
class _FakeChatModel:
    """Minimal stand-in for a bound LangChain chat model.

    Records invocations and returns a scripted ``AIMessage``. ``bind_tools``
    returns a variant that remembers the tools it was bound with, mirroring the
    real ``ChatOpenAI`` surface the client depends on.
    """

    def __init__(self, message: AIMessage, *, raises: Sequence[Exception] | None = None) -> None:
        self._message = message
        self._raises = list(raises or [])
        self.bound_tools: list[dict[str, Any]] | None = None
        self.invocations = 0

    def bind_tools(self, tools: list[dict[str, Any]]) -> _FakeChatModel:
        self.bound_tools = tools
        return self

    def invoke(self, messages: Any) -> AIMessage:
        self.invocations += 1
        if self._raises:
            raise self._raises.pop(0)
        return self._message


def _client_with(model: Any) -> OpenAILLMClient:
    return OpenAILLMClient(settings=Settings(), chat_model=model, retry_policy=_FAST)


def test_openai_client_extracts_content_and_usage() -> None:
    ai = AIMessage(
        content="hello world",
        usage_metadata={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
    )
    client = _client_with(_FakeChatModel(ai))
    result = client.complete([Message.user("hi")])

    assert result.content == "hello world"
    assert result.usage.total_tokens == 20
    assert client.total_tokens == 20


def test_openai_client_parses_tool_calls() -> None:
    from langchain_core.messages.tool import ToolCall as LcToolCall

    ai = AIMessage(
        content="",
        tool_calls=[LcToolCall(name="keyword_metrics", args={"keywords": ["seo"]}, id="call_9")],
        usage_metadata={"input_tokens": 4, "output_tokens": 1, "total_tokens": 5},
    )
    client = _client_with(_FakeChatModel(ai))
    result = client.complete([Message.user("look these up")])

    assert result.has_tool_calls is True
    call = result.tool_calls[0]
    assert call.name == "keyword_metrics"
    assert call.args == {"keywords": ["seo"]}
    assert call.id == "call_9"


def test_openai_client_binds_tools_for_the_model_to_choose() -> None:
    ai = AIMessage(
        content="ok", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
    )
    fake = _FakeChatModel(ai)
    client = _client_with(fake)

    tools = build_dataforseo_tools(DataForSeoClient(retry_policy=_FAST))
    specs = specs_from_tools(list(tools.values()))
    client.complete([Message.user("go")], tools=specs)

    assert fake.bound_tools is not None
    names = {t["function"]["name"] for t in fake.bound_tools}
    assert names == set(tools)


def test_openai_client_accumulates_tokens_across_calls() -> None:
    ai = AIMessage(
        content="x", usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
    )
    client = _client_with(_FakeChatModel(ai))
    client.complete([Message.user("1")])
    client.complete([Message.user("2")])
    assert client.total_tokens == 10


def test_openai_client_usage_defaults_to_zero_when_absent() -> None:
    ai = AIMessage(content="no usage reported")
    client = _client_with(_FakeChatModel(ai))
    result = client.complete([Message.user("hi")])
    assert result.usage.total_tokens == 0


def test_openai_client_retries_transient_error_then_succeeds() -> None:
    class RateLimitError(Exception):
        pass

    ai = AIMessage(
        content="recovered",
        usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    )
    fake = _FakeChatModel(ai, raises=[RateLimitError("slow down")])
    client = _client_with(fake)

    result = client.complete([Message.user("hi")])
    assert result.content == "recovered"
    assert fake.invocations == 2  # failed once, retried, succeeded


def test_openai_client_does_not_retry_non_retryable_error() -> None:
    from app.resilience.errors import NonRetryableError

    class AuthenticationError(Exception):
        status_code = 401

    fake = _FakeChatModel(
        AIMessage(content="never"),
        raises=[AuthenticationError("bad key"), AuthenticationError("bad key")],
    )
    client = _client_with(fake)

    with pytest.raises(NonRetryableError):
        client.complete([Message.user("hi")])
    assert fake.invocations == 1  # not retried


def test_openai_client_retries_on_5xx_status_then_exhausts() -> None:
    from app.resilience.errors import RetryableError

    class ServerBlip(Exception):
        status_code = 503

    fake = _FakeChatModel(
        AIMessage(content="never"),
        raises=[ServerBlip("a"), ServerBlip("b"), ServerBlip("c")],
    )
    client = _client_with(fake)

    with pytest.raises(RetryableError):
        client.complete([Message.user("hi")])
    assert fake.invocations == 3  # all attempts used


# --------------------------------------------------------------------------- #
# Factory: build_llm selects the right client from settings
# --------------------------------------------------------------------------- #
def test_build_llm_returns_mock_without_key() -> None:
    client = build_llm(Settings(LLM_MODE="auto", OPENAI_API_KEY=""))
    assert isinstance(client, ScriptedLLMClient)


def test_build_llm_forces_mock_mode() -> None:
    client = build_llm(Settings(LLM_MODE="mock", OPENAI_API_KEY="sk-real"))
    assert isinstance(client, ScriptedLLMClient)


def test_build_llm_uses_injected_chat_model_as_real_client() -> None:
    ai = AIMessage(
        content="ok", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
    )
    client = build_llm(Settings(LLM_MODE="mock"), chat_model=_FakeChatModel(ai))
    assert isinstance(client, OpenAILLMClient)
    assert client.complete([Message.user("hi")]).content == "ok"


def test_settings_openai_mode_requires_key() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings(LLM_MODE="openai", OPENAI_API_KEY="")


def test_settings_use_real_llm_property() -> None:
    assert Settings(LLM_MODE="auto", OPENAI_API_KEY="sk-x").use_real_llm is True
    assert Settings(LLM_MODE="auto", OPENAI_API_KEY="").use_real_llm is False
    assert Settings(LLM_MODE="mock", OPENAI_API_KEY="sk-x").use_real_llm is False
    assert Settings(LLM_MODE="openai", OPENAI_API_KEY="sk-x").use_real_llm is True
