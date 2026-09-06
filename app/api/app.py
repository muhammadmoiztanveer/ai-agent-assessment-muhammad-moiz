"""FastAPI application factory.

Builds the production-shaped app: structured logging, permissive CORS for the
(beyond-spec) frontend, database initialization on startup, the uniform error
envelope, and the versioned API routers (profiles, runs, queries, recommendations)
plus liveness endpoints.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.routes import all_routers
from app.config import Settings, get_settings
from app.db.database import init_db
from app.observability import configure_logging
from app.observability.logging import get_logger
from app.services.run_queue import init_run_queue, shutdown_run_queue

_logger = get_logger("api")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Optional settings override (useful for tests). Falls back to
            the process-wide cached settings.

    Returns:
        A configured :class:`fastapi.FastAPI` instance.
    """
    settings = settings or get_settings()

    # Configure structured JSON logging + secret redaction for the whole process.
    configure_logging(level=settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Ensure the database schema exists before the app serves traffic.
        init_db(settings)
        # Start the background worker pool for async runs (spec §4.2 bonus).
        init_run_queue(settings)
        _logger.info("api.startup", mode=settings.dataforseo_mode, llm=settings.llm_mode)
        yield
        # Drain in-flight background runs before exiting.
        shutdown_run_queue(wait=True)
        _logger.info("api.shutdown")

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        summary="Agentic search-visibility intelligence pipeline (LangGraph DAG) over a JSON API.",
        lifespan=lifespan,
    )

    # CORS: open in this assessment build so the local dashboard can call the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    install_error_handlers(app)

    for router in all_routers:
        app.include_router(router)

    @app.get("/health", tags=["meta"], summary="Liveness probe")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": settings.api_title,
            "version": settings.api_version,
        }

    return app


# Module-level ASGI app for `uvicorn app.api.app:app`.
app = create_app()


__all__ = ["app", "create_app"]
