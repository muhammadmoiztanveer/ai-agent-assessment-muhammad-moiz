"""LLM layer: provider client factory, tool binding, token accounting, prompts."""

from __future__ import annotations

from app.llm.base import (
    LLMClient,
    LLMRequest,
    LLMResponse,
    Message,
    Role,
    TokenUsage,
    ToolCall,
    ToolSpec,
    UsageCallback,
    specs_from_tools,
)
from app.llm.client import OpenAILLMClient, build_llm
from app.llm.mock import Responder, ScriptedLLMClient
from app.llm.prompts import AGENT_PROMPTS, PROMPT_VERSION, get_prompt

__all__ = [
    "AGENT_PROMPTS",
    "PROMPT_VERSION",
    "LLMClient",
    "LLMRequest",
    "LLMResponse",
    "Message",
    "OpenAILLMClient",
    "Responder",
    "Role",
    "ScriptedLLMClient",
    "TokenUsage",
    "ToolCall",
    "ToolSpec",
    "UsageCallback",
    "build_llm",
    "get_prompt",
    "specs_from_tools",
]
