"""Entrypoint for ``python -m app``.

Boots the FastAPI application with Uvicorn using host/port from configuration.
"""

from __future__ import annotations

import uvicorn

from app.config import get_settings


def main() -> None:
    """Start the API server."""
    settings = get_settings()
    uvicorn.run(
        "app.api.app:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
