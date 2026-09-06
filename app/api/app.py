"""FastAPI application factory.

Phase 0 provides a minimal but production-shaped app: metadata, permissive CORS
for the (beyond-spec) frontend, and liveness/readiness endpoints so ``make run``
boots cleanly. Routers, exception handlers, and DB lifecycle are wired in later
phases.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Optional settings override (useful for tests). Falls back to
            the process-wide cached settings.

    Returns:
        A configured :class:`fastapi.FastAPI` instance.
    """
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        summary="Agentic search-visibility intelligence pipeline (LangGraph DAG) over a JSON API.",
    )

    # CORS: open in this assessment build so the local dashboard can call the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
