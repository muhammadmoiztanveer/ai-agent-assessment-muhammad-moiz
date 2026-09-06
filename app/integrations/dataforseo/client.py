"""DataForSEO HTTP client with mode switching and built-in resilience.

One method per logical endpoint (see :mod:`.endpoints`). Every call is wrapped
in the shared resilience machinery:

- **Timeouts:** explicit connect + read timeouts from settings on every request
  (no unbounded waits).
- **Retry:** transient failures (timeouts, connection errors, 429, 5xx) are
  retried with exponential backoff + full jitter; deterministic failures fail
  fast (see :mod:`app.resilience`).
- **Circuit breaker:** consecutive dependency failures trip a breaker that then
  fails fast for a cooldown, so we stop hammering a dead dependency.

Three modes select where data comes from (``DATAFORSEO_MODE``):

- ``mock`` *(default)* — deterministic local fixtures; no network, no credentials.
- ``live`` — real DataForSEO API over HTTP with Basic auth.
- ``stub`` — minimal static payloads (a documented, dependency-free fallback).

A ``mock_hook`` seam lets tests and the README's simulated-failure walkthrough
inject transient errors deterministically *through the real retry/breaker path*,
so failure handling is exercised end-to-end without a network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.integrations.dataforseo import endpoints as ep
from app.integrations.dataforseo.mock import fixtures
from app.observability.logging import get_logger
from app.resilience.circuit_breaker import CircuitBreaker
from app.resilience.errors import (
    ClassifiedError,
    NonRetryableError,
    RetryableError,
    classify,
    is_retryable,
)
from app.resilience.retry import RetryAttempt, RetryPolicy, retry_call

_logger = get_logger("dataforseo")

# A hook invoked in mock mode before returning a fixture: ``(path, payload)``.
# It may raise (e.g. an ``httpx`` transport error) to simulate a transient fault.
MockHook = Callable[[str, dict[str, Any]], None]


def _raise_for_response(response: httpx.Response) -> None:
    """Raise the matching resilience error if an HTTP response is an error."""
    if response.status_code < 400:
        return
    classified = classify(response)
    if classified.retryable:
        raise RetryableError(classified)
    raise NonRetryableError(classified)


class DataForSeoClient:
    """Client for the subset of DataForSEO endpoints this system uses."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        retry_policy: RetryPolicy | None = None,
        breaker: CircuitBreaker | None = None,
        http_client: httpx.Client | None = None,
        mock_hook: MockHook | None = None,
        on_retry: Callable[[RetryAttempt], None] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._policy = retry_policy or RetryPolicy.from_settings(self._settings)
        self._breaker = breaker or CircuitBreaker.from_settings("dataforseo", self._settings)
        self._external_http = http_client is not None
        self._http = http_client
        self._mock_hook = mock_hook
        self._on_retry = on_retry
        self._retry_count = 0

    # --- lifecycle -------------------------------------------------------- #
    @property
    def mode(self) -> str:
        return self._settings.dataforseo_mode

    @property
    def last_retry_count(self) -> int:
        """Number of retries performed by the most recent call (0 if none)."""
        return self._retry_count

    def close(self) -> None:
        """Close the owned HTTP client, if any."""
        if self._http is not None and not self._external_http:
            self._http.close()
            self._http = None

    def __enter__(self) -> DataForSeoClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- logical endpoints (one method each) ------------------------------ #
    def serp_organic_search(
        self,
        *,
        keyword: str,
        location_code: int = 2840,
        language_code: str = "en",
        depth: int = 10,
    ) -> dict[str, Any]:
        """Fetch live Google organic SERP results for a keyword."""
        payload = {
            "keyword": keyword,
            "location_code": location_code,
            "language_code": language_code,
            "depth": depth,
        }
        return self._request(
            ep.SERP_ORGANIC,
            payload,
            lambda: fixtures.serp_organic(
                keyword,
                location_code=location_code,
                language_code=language_code,
                depth=depth,
            ),
        )

    def ai_overview_search(
        self,
        *,
        keyword: str,
        location_code: int = 2840,
        language_code: str = "en",
    ) -> dict[str, Any]:
        """Fetch the Google AI Overview / AI Mode block for a keyword."""
        payload = {
            "keyword": keyword,
            "location_code": location_code,
            "language_code": language_code,
        }
        return self._request(
            ep.AI_OVERVIEW,
            payload,
            lambda: fixtures.ai_overview(
                keyword, location_code=location_code, language_code=language_code
            ),
        )

    def llm_visibility_lookup(
        self,
        *,
        prompt: str,
        brand: str,
        models: list[str] | None = None,
    ) -> dict[str, Any]:
        """Look up whether a brand is cited in LLM assistant answers for a prompt."""
        resolved_models = models or ["gpt-4o", "gemini-1.5-pro", "perplexity"]
        payload = {"prompt": prompt, "brand": brand, "models": resolved_models}
        return self._request(
            ep.LLM_VISIBILITY,
            payload,
            lambda: fixtures.llm_visibility(prompt, brand=brand, models=resolved_models),
        )

    def keyword_metrics(
        self,
        *,
        keywords: list[str],
        location_code: int = 2840,
        language_code: str = "en",
    ) -> dict[str, Any]:
        """Fetch search volume + competitive difficulty for keywords."""
        payload = {
            "keywords": keywords,
            "location_code": location_code,
            "language_code": language_code,
        }
        return self._request(
            ep.KEYWORD_METRICS,
            payload,
            lambda: fixtures.keyword_metrics(
                keywords, location_code=location_code, language_code=language_code
            ),
        )

    # --- request pipeline ------------------------------------------------- #
    def _request(
        self,
        endpoint: ep.Endpoint,
        payload: dict[str, Any],
        mock_builder: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute one endpoint call through the retry + circuit-breaker pipeline."""
        self._retry_count = 0

        def operation() -> dict[str, Any]:
            if self._settings.dataforseo_mode == "live":
                return self._live_request(endpoint, payload)
            if self._settings.dataforseo_mode == "stub":
                return self._stub_response(endpoint, payload)
            # mock (default): allow deterministic fault injection, then build fixture.
            if self._mock_hook is not None:
                self._mock_hook(endpoint.path, payload)
            return mock_builder()

        def guarded() -> dict[str, Any]:
            # Only genuine dependency (retryable) failures count against the breaker;
            # client mistakes (bad args, 4xx) should not trip it.
            return self._breaker.call(operation, record_failure_on=is_retryable)

        def track_retry(attempt: RetryAttempt) -> None:
            self._retry_count += 1
            _logger.warning(
                "dataforseo.retry",
                endpoint=endpoint.name,
                attempt=attempt.attempt,
                delay_s=attempt.delay_s,
                error_code=attempt.error.code,
            )
            if self._on_retry is not None:
                self._on_retry(attempt)

        return retry_call(guarded, policy=self._policy, on_retry=track_retry)

    def _live_request(self, endpoint: ep.Endpoint, payload: dict[str, Any]) -> dict[str, Any]:
        """Perform a real DataForSEO HTTP call (Basic auth, explicit timeouts)."""
        client = self._get_http_client()
        # DataForSEO's /live/ endpoints accept a JSON array of task objects.
        response = client.request(endpoint.method, endpoint.path, json=[payload])
        _raise_for_response(response)
        data: dict[str, Any] = response.json()
        return data

    def _get_http_client(self) -> httpx.Client:
        """Lazily build (and reuse) the configured httpx client for live mode."""
        if self._http is None:
            timeout = httpx.Timeout(
                connect=self._settings.http_connect_timeout_s,
                read=self._settings.http_read_timeout_s,
                write=self._settings.http_read_timeout_s,
                pool=self._settings.http_connect_timeout_s,
            )
            auth = httpx.BasicAuth(
                self._settings.dataforseo_login, self._settings.dataforseo_password
            )
            self._http = httpx.Client(
                base_url=self._settings.dataforseo_base_url,
                auth=auth,
                timeout=timeout,
                headers={"Content-Type": "application/json"},
            )
        return self._http

    def _stub_response(self, endpoint: ep.Endpoint, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a minimal, dependency-free static payload for ``stub`` mode."""
        return {
            "version": "stub",
            "status_code": 20000,
            "status_message": "Ok.",
            "cost": 0.0,
            "tasks_count": 1,
            "tasks_error": 0,
            "tasks": [
                {
                    "id": "stub-task",
                    "status_code": 20000,
                    "status_message": "Ok.",
                    "result_count": 0,
                    "path": ["v3"],
                    "result": [],
                }
            ],
        }


def build_client(settings: Settings | None = None, **kwargs: Any) -> DataForSeoClient:
    """Construct a :class:`DataForSeoClient` from settings (convenience factory)."""
    return DataForSeoClient(settings, **kwargs)


__all__ = [
    "ClassifiedError",
    "DataForSeoClient",
    "MockHook",
    "build_client",
]
