"""Shared pytest fixtures for the Phase 9 spec-mandated suite.

Everything here is hermetic: a fresh temp-file SQLite database per test, the
default keyless DataForSEO ``mock`` mode, and a deterministic scripted LLM. No
network and no credentials are required, so the whole suite is fast and
reproducible (spec §5).

The helpers below are intentionally small and reused across the canonical test
files (``test_happy_path``, ``test_failure_retry``, ``test_fallback_degradation``,
``test_tool_validation``, ``test_api_contracts``, ``test_opportunity_score``) so
each file stays focused on the behaviour it is proving.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.agents.types import ProfileContext
from app.api.app import create_app
from app.config import Settings
from app.db.database import init_engine
from app.graph import build_dependencies, run_pipeline
from app.graph.dependencies import PipelineDependencies
from app.graph.state import PipelineState
from app.integrations.dataforseo.client import DataForSeoClient
from app.llm.mock import ScriptedLLMClient
from app.resilience.retry import RetryPolicy

# A no-sleep retry policy so failure tests exhaust retries instantly.
FAST_RETRY = RetryPolicy(max_attempts=3, base_delay_s=0.0, max_delay_s=0.0, jitter=False)


def make_settings(**overrides: object) -> Settings:
    """Build default (mock-mode, keyless) settings with optional overrides."""
    return Settings(**overrides)  # type: ignore[arg-type]


def make_profile(
    *,
    name: str = "Surfer SEO",
    domain: str = "https://www.surferseo.com",
    industry: str = "SEO software",
    competitors: tuple[str, ...] = ("ahrefs.com", "semrush.com"),
) -> ProfileContext:
    """A representative brand profile for pipeline-level tests."""
    return ProfileContext(
        name=name,
        domain=domain,
        industry=industry,
        competitors=competitors,
    )


def make_deps(
    client: DataForSeoClient | None = None,
    *,
    settings: Settings | None = None,
) -> PipelineDependencies:
    """Pipeline dependencies bound to a client and a deterministic keyless LLM."""
    settings = settings or make_settings()
    client = client or DataForSeoClient(settings=settings, retry_policy=FAST_RETRY)
    return build_dependencies(settings, client=client, llm=ScriptedLLMClient())


def run_full_pipeline(
    client: DataForSeoClient | None = None,
    *,
    research_question: str = "best project management software",
    settings: Settings | None = None,
) -> PipelineState:
    """Run one full pipeline end-to-end and return the final state."""
    settings = settings or make_settings()
    return run_pipeline(
        profile=make_profile(),
        research_question=research_question,
        settings=settings,
        deps=make_deps(client, settings=settings),
    )


@pytest.fixture
def api_client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    """A FastAPI ``TestClient`` backed by a fresh temp-file SQLite database."""
    db_file = tmp_path / "phase9.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    settings = Settings()
    init_engine(settings, create_tables=True)
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def create_profile(api_client: TestClient) -> Callable[..., str]:
    """Factory that registers a profile and returns its ``profile_uuid``."""

    def _create(
        *,
        name: str = "Surfer SEO",
        domain: str = "surferseo.com",
        industry: str = "SEO software",
        competitors: list[str] | None = None,
    ) -> str:
        resp = api_client.post(
            "/api/v1/profiles",
            json={
                "name": name,
                "domain": domain,
                "industry": industry,
                "description": "Content optimization platform",
                "competitors": competitors if competitors is not None else ["semrush.com"],
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["profile_uuid"]

    return _create
