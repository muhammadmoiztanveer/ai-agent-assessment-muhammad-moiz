"""Phase 4 tests: DataForSEO client + validating tools.

Covers the three behaviours the spec calls out for tools/integration:
  1. happy-path mock round-trips (deterministic, correct envelope shape),
  2. tool-argument validation (malformed/partial args rejected gracefully),
  3. failure handling — injected transient faults retry then succeed, exhausted
     retries surface a retryable error, and a tripped circuit breaker fails fast.

Also exercises the ``live`` path via an injected ``httpx.MockTransport`` (no
network) and the ``stub`` mode. All tests are hermetic and fast.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.integrations.dataforseo.client import DataForSeoClient
from app.resilience.circuit_breaker import CircuitBreaker
from app.resilience.retry import RetryPolicy
from app.tools.base import ToolResult, ValidatedTool
from app.tools.dataforseo_tools import build_dataforseo_tools
from app.tools.schemas import SerpOrganicSearchArgs

# A retry policy that never actually sleeps, for fast deterministic tests.
_FAST = RetryPolicy(max_attempts=3, base_delay_s=0.0, max_delay_s=0.0, jitter=False)


def _mock_client(**kwargs: object) -> DataForSeoClient:
    """A client in the default mock mode with a fast, no-sleep retry policy."""
    return DataForSeoClient(retry_policy=_FAST, **kwargs)  # type: ignore[arg-type]


def _tools(client: DataForSeoClient) -> dict[str, ValidatedTool]:
    return build_dataforseo_tools(client)


# --------------------------------------------------------------------------- #
# Registry + happy path
# --------------------------------------------------------------------------- #
def test_registry_has_one_tool_per_logical_call() -> None:
    tools = _tools(_mock_client())
    assert set(tools) == {
        "serp_organic_search",
        "ai_overview_search",
        "llm_visibility_lookup",
        "keyword_metrics",
    }


def test_serp_happy_path_shape() -> None:
    tools = _tools(_mock_client())
    result = tools["serp_organic_search"].invoke({"keyword": "best crm software", "depth": 5})

    assert result.ok is True
    assert result.error is None
    assert result.args["keyword"] == "best crm software"

    envelope = result.data
    assert envelope is not None
    assert envelope["status_code"] == 20000
    items = envelope["tasks"][0]["result"][0]["items"]
    assert len(items) == 5
    assert all({"domain", "rank_absolute", "url"} <= set(item) for item in items)


def test_keyword_metrics_happy_path_shape() -> None:
    tools = _tools(_mock_client())
    result = tools["keyword_metrics"].invoke({"keywords": ["seo tools", "ai search"]})

    assert result.ok is True
    items = result.data["tasks"][0]["result"][0]["items"]  # type: ignore[index]
    assert [i["keyword"] for i in items] == ["seo tools", "ai search"]
    for item in items:
        assert item["keyword_info"]["search_volume"] >= 0
        assert 0 <= item["keyword_properties"]["keyword_difficulty"] <= 100


def test_ai_overview_and_llm_visibility_happy_path() -> None:
    tools = _tools(_mock_client())

    ov = tools["ai_overview_search"].invoke({"keyword": "project management"})
    assert ov.ok is True
    ai_item = ov.data["tasks"][0]["result"][0]["items"][0]  # type: ignore[index]
    assert ai_item["type"] == "ai_overview"
    assert len(ai_item["references"]) >= 1

    lv = tools["llm_visibility_lookup"].invoke(
        {"prompt": "best seo tool", "brand": "surferseo.com"}
    )
    assert lv.ok is True
    responses = lv.data["tasks"][0]["result"][0]["responses"]  # type: ignore[index]
    assert {"gpt-4o", "gemini-1.5-pro", "perplexity"} == {r["model"] for r in responses}


def test_mock_responses_are_deterministic() -> None:
    tools_a = _tools(_mock_client())
    tools_b = _tools(_mock_client())
    a = tools_a["serp_organic_search"].invoke({"keyword": "same query", "depth": 7})
    b = tools_b["serp_organic_search"].invoke({"keyword": "same query", "depth": 7})
    assert a.data == b.data


# --------------------------------------------------------------------------- #
# Tool-argument validation (validate BEFORE calling)
# --------------------------------------------------------------------------- #
def test_blank_keyword_is_rejected_without_calling() -> None:
    calls = {"n": 0}

    def hook(_path: str, _payload: dict) -> None:
        calls["n"] += 1

    tools = _tools(_mock_client(mock_hook=hook))
    result = tools["serp_organic_search"].invoke({"keyword": "   "})

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "invalid_tool_args"
    assert result.error.retryable is False
    # The underlying call must never have run.
    assert calls["n"] == 0


def test_missing_required_field_is_rejected() -> None:
    tools = _tools(_mock_client())
    result = tools["keyword_metrics"].invoke({})
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "invalid_tool_args"
    assert any(e["field"] == "keywords" for e in result.error.detail["errors"])


def test_unknown_field_is_rejected() -> None:
    tools = _tools(_mock_client())
    result = tools["ai_overview_search"].invoke({"keyword": "x", "surprise": 1})
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "invalid_tool_args"


def test_out_of_range_depth_is_rejected() -> None:
    tools = _tools(_mock_client())
    result = tools["serp_organic_search"].invoke({"keyword": "x", "depth": 500})
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "invalid_tool_args"


def test_empty_keyword_list_is_rejected() -> None:
    tools = _tools(_mock_client())
    result = tools["keyword_metrics"].invoke({"keywords": []})
    assert result.ok is False


def test_validation_error_detail_excludes_raw_input() -> None:
    tools = _tools(_mock_client())
    result = tools["serp_organic_search"].invoke({"keyword": ""})
    assert result.error is not None
    errors = result.error.detail["errors"]
    assert isinstance(errors, list)
    # Only compact {field,type,message} entries — no raw input/url leakage.
    assert all(set(e) == {"field", "type", "message"} for e in errors)


def test_typed_args_instance_is_accepted() -> None:
    tools = _tools(_mock_client())
    args = SerpOrganicSearchArgs(keyword="typed path", depth=3)
    result = tools["serp_organic_search"].invoke(args)
    assert result.ok is True


# --------------------------------------------------------------------------- #
# Failure handling: retry, exhaustion, circuit breaker
# --------------------------------------------------------------------------- #
def test_transient_failure_retries_then_succeeds() -> None:
    state = {"n": 0}

    def hook(_path: str, _payload: dict) -> None:
        state["n"] += 1
        if state["n"] < 3:
            raise httpx.ReadTimeout("transient")

    client = _mock_client(mock_hook=hook)
    tools = _tools(client)
    result = tools["serp_organic_search"].invoke({"keyword": "flaky"})

    assert result.ok is True
    assert client.last_retry_count == 2  # failed twice, third attempt succeeded


def test_exhausted_retries_returns_retryable_failure() -> None:
    def hook(_path: str, _payload: dict) -> None:
        raise httpx.ConnectError("dependency down")

    # Large threshold so the breaker doesn't trip during this test.
    client = _mock_client(
        mock_hook=hook,
        breaker=CircuitBreaker("dfs", fail_threshold=99, cooldown_s=30.0),
    )
    tools = _tools(client)
    result = tools["serp_organic_search"].invoke({"keyword": "down"})

    assert result.ok is False
    assert result.error is not None
    assert result.error.retryable is True
    assert result.error.code == "connection_error"
    assert client.last_retry_count == 2  # 3 attempts total


def test_circuit_breaker_opens_and_fails_fast() -> None:
    def hook(_path: str, _payload: dict) -> None:
        raise httpx.ConnectError("dependency down")

    breaker = CircuitBreaker("dfs", fail_threshold=2, cooldown_s=30.0)
    # One attempt per call so each failed call records exactly one breaker failure.
    client = DataForSeoClient(
        retry_policy=RetryPolicy(max_attempts=1, base_delay_s=0.0, jitter=False),
        mock_hook=hook,
        breaker=breaker,
    )
    tools = _tools(client)

    # Two failing calls trip the breaker (threshold = 2).
    tools["serp_organic_search"].invoke({"keyword": "a"})
    tools["serp_organic_search"].invoke({"keyword": "b"})

    # The next call is rejected immediately by the open circuit.
    result = tools["serp_organic_search"].invoke({"keyword": "c"})
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "circuit_open"
    assert result.error.retryable is False


# --------------------------------------------------------------------------- #
# Live mode (via injected MockTransport) + stub mode
# --------------------------------------------------------------------------- #
def _live_settings() -> Settings:
    return Settings(
        DATAFORSEO_MODE="live",
        DATAFORSEO_LOGIN="user",
        DATAFORSEO_PASSWORD="pass",
    )


def test_live_mode_success_via_mock_transport() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={"status_code": 20000, "tasks": [{"result": [{"keyword": "live!"}]}]},
        )

    # Inject a transport-backed client configured exactly as the live client is
    # (Basic auth), so the end-to-end request path is exercised without a network.
    http = httpx.Client(
        base_url="https://api.dataforseo.com",
        auth=httpx.BasicAuth("user", "pass"),
        transport=httpx.MockTransport(handler),
    )
    client = DataForSeoClient(_live_settings(), retry_policy=_FAST, http_client=http)
    tools = _tools(client)

    result = tools["serp_organic_search"].invoke({"keyword": "live test"})
    assert result.ok is True
    assert result.data["tasks"][0]["result"][0]["keyword"] == "live!"  # type: ignore[index]
    assert "/v3/serp/google/organic/live/advanced" in captured["url"]  # type: ignore[operator]
    assert str(captured["auth"]).startswith("Basic ")  # Basic auth header was sent
    # DataForSEO /live/ endpoints take a JSON *array* of task objects.
    assert captured["body"].strip().startswith(b"[")  # type: ignore[union-attr]


def test_live_client_is_configured_with_basic_auth() -> None:
    """Our own live-mode builder attaches Basic auth (no injected client)."""
    client = DataForSeoClient(_live_settings(), retry_policy=_FAST)
    http = client._get_http_client()
    try:
        assert type(http._auth).__name__ == "BasicAuth"
        assert str(http.base_url).rstrip("/") == "https://api.dataforseo.com"
    finally:
        client.close()


def test_live_mode_401_is_non_retryable_failure() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    http = httpx.Client(
        base_url="https://api.dataforseo.com",
        transport=httpx.MockTransport(handler),
    )
    client = DataForSeoClient(_live_settings(), retry_policy=_FAST, http_client=http)
    tools = _tools(client)

    result = tools["serp_organic_search"].invoke({"keyword": "no auth"})
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "unauthorized"
    assert result.error.retryable is False
    assert attempts["n"] == 1  # not retried


def test_live_mode_500_is_retried_then_fails() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503, json={"error": "unavailable"})

    http = httpx.Client(
        base_url="https://api.dataforseo.com",
        transport=httpx.MockTransport(handler),
    )
    client = DataForSeoClient(
        _live_settings(),
        retry_policy=RetryPolicy(max_attempts=3, base_delay_s=0.0, jitter=False),
        http_client=http,
        breaker=CircuitBreaker("dfs", fail_threshold=99),
    )
    tools = _tools(client)

    result = tools["serp_organic_search"].invoke({"keyword": "flaky server"})
    assert result.ok is False
    assert result.error is not None
    assert result.error.retryable is True
    assert attempts["n"] == 3  # all attempts used


def test_stub_mode_returns_empty_envelope() -> None:
    settings = Settings(DATAFORSEO_MODE="stub")
    client = DataForSeoClient(settings, retry_policy=_FAST)
    tools = _tools(client)
    result = tools["keyword_metrics"].invoke({"keywords": ["x"]})
    assert result.ok is True
    assert result.data["tasks"][0]["result"] == []  # type: ignore[index]


# --------------------------------------------------------------------------- #
# ToolResult helpers + JSON schema
# --------------------------------------------------------------------------- #
def test_tool_result_as_dict_is_json_safe() -> None:
    tools = _tools(_mock_client())
    ok = tools["serp_organic_search"].invoke({"keyword": "x"}).as_dict()
    assert ok["ok"] is True and ok["error"] is None

    bad = tools["serp_organic_search"].invoke({"keyword": ""}).as_dict()
    assert bad["ok"] is False
    assert bad["error"]["code"] == "invalid_tool_args"


def test_tool_exposes_json_schema_for_binding() -> None:
    tools = _tools(_mock_client())
    schema = tools["serp_organic_search"].json_schema()
    assert schema["type"] == "object"
    assert "keyword" in schema["properties"]
    assert "keyword" in schema["required"]


def test_tool_result_factories() -> None:
    ok = ToolResult.success("t", {"a": 1}, {"k": "v"})
    assert ok.ok and ok.retryable is False
    from app.resilience.errors import ClassifiedError

    fail = ToolResult.failure("t", ClassifiedError(code="x", retryable=True, message="m"))
    assert fail.ok is False and fail.retryable is True
