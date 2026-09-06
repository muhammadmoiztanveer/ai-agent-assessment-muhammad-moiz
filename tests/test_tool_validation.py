"""Mandated test #4 — tool-call argument validation (spec §5, §3.3).

The LLM proposes tool arguments; our code must validate them **before** making any
real API call, and malformed / partial arguments must be handled gracefully
(never crash). These tests prove:

- Each tool exposes a typed JSON schema for LLM binding.
- Blank / missing / unknown / out-of-range arguments are rejected as a clean
  non-retryable :class:`ToolResult` with a redaction-safe error detail.
- The underlying API call is never reached when arguments are invalid.
- A bad-args call routed through the Retrieval agent degrades gracefully rather
  than raising — so a bad plan cannot crash the graph.
"""

from __future__ import annotations

from app.agents.retrieval import RetrievalAgent
from app.agents.types import PlannedCall, RetrievalPlan
from app.integrations.dataforseo.client import DataForSeoClient
from app.tools.dataforseo_tools import build_dataforseo_tools
from app.tools.schemas import SerpOrganicSearchArgs
from tests.conftest import FAST_RETRY, make_settings


def _tools(client: DataForSeoClient | None = None):  # type: ignore[no-untyped-def]
    client = client or DataForSeoClient(settings=make_settings(), retry_policy=FAST_RETRY)
    return build_dataforseo_tools(client)


# --------------------------------------------------------------------------- #
# Schemas are typed and bindable
# --------------------------------------------------------------------------- #
def test_each_tool_exposes_a_json_schema() -> None:
    tools = _tools()
    schema = tools["serp_organic_search"].json_schema()
    assert schema["type"] == "object"
    assert "keyword" in schema["properties"]
    assert "keyword" in schema["required"]


# --------------------------------------------------------------------------- #
# Validation happens BEFORE the real call
# --------------------------------------------------------------------------- #
def test_blank_required_arg_is_rejected_without_calling() -> None:
    calls = {"n": 0}

    def hook(_path: str, _payload: dict) -> None:
        calls["n"] += 1

    tools = _tools(
        DataForSeoClient(settings=make_settings(), retry_policy=FAST_RETRY, mock_hook=hook)
    )
    result = tools["serp_organic_search"].invoke({"keyword": "   "})

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "invalid_tool_args"
    assert result.error.retryable is False
    assert calls["n"] == 0  # the API was never called


def test_missing_required_field_is_rejected() -> None:
    result = _tools()["keyword_metrics"].invoke({})
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "invalid_tool_args"
    assert any(e["field"] == "keywords" for e in result.error.detail["errors"])


def test_unknown_field_is_rejected() -> None:
    result = _tools()["ai_overview_search"].invoke({"keyword": "x", "not_a_field": 1})
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "invalid_tool_args"


def test_out_of_range_value_is_rejected() -> None:
    result = _tools()["serp_organic_search"].invoke({"keyword": "x", "depth": 9999})
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "invalid_tool_args"


def test_empty_keyword_list_is_rejected() -> None:
    result = _tools()["keyword_metrics"].invoke({"keywords": []})
    assert result.ok is False


def test_valid_args_pass_and_return_data() -> None:
    result = _tools()["serp_organic_search"].invoke({"keyword": "best crm software", "depth": 5})
    assert result.ok is True
    assert result.error is None
    assert result.data is not None


def test_typed_args_instance_is_accepted() -> None:
    args = SerpOrganicSearchArgs(keyword="typed path", depth=3)
    result = _tools()["serp_organic_search"].invoke(args)
    assert result.ok is True


# --------------------------------------------------------------------------- #
# Error detail is redaction-safe
# --------------------------------------------------------------------------- #
def test_validation_error_detail_is_compact_and_leak_free() -> None:
    result = _tools()["serp_organic_search"].invoke({"keyword": ""})
    assert result.error is not None
    errors = result.error.detail["errors"]
    assert isinstance(errors, list)
    # Only compact {field,type,message} entries — no raw input echoed back.
    assert all(set(e) == {"field", "type", "message"} for e in errors)


# --------------------------------------------------------------------------- #
# A bad-args plan cannot crash the graph
# --------------------------------------------------------------------------- #
def test_retrieval_agent_handles_bad_args_gracefully() -> None:
    agent = RetrievalAgent(tools=_tools())
    plan = RetrievalPlan(
        research_question="q",
        calls=(
            # One valid call and one with a blank required keyword.
            PlannedCall(tool="keyword_metrics", args={"keywords": ["seo tools"]}, rationale="ok"),
            PlannedCall(tool="serp_organic_search", args={"keyword": ""}, rationale="bad"),
        ),
    )

    outcome = agent.run(plan)  # must not raise

    assert any(r.ok for r in outcome.results)  # the good call succeeded
    assert outcome.errors  # the bad call was captured as a classified error
    assert any(e.code == "invalid_tool_args" for e in outcome.errors)
