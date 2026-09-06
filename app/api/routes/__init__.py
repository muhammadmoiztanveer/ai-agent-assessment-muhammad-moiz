"""HTTP route modules (profiles, runs, queries, recommendations)."""

from __future__ import annotations

from app.api.routes.profiles import router as profiles_router
from app.api.routes.queries import router as queries_router
from app.api.routes.recommendations import router as recommendations_router
from app.api.routes.runs import router as runs_router
from app.api.routes.runs import runs_router as run_status_router

# Order matters only for OpenAPI grouping; paths are unambiguous.
all_routers = [
    profiles_router,
    runs_router,
    run_status_router,
    queries_router,
    recommendations_router,
]

__all__ = [
    "all_routers",
    "profiles_router",
    "queries_router",
    "recommendations_router",
    "run_status_router",
    "runs_router",
]
