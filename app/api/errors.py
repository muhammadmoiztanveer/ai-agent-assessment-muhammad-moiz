"""Uniform error envelope and FastAPI exception handlers.

Every error the API returns shares one shape so clients can parse failures
uniformly::

    {"error": {"code": "not_found", "message": "...", "details": {...}}}

Domain code raises :class:`APIError` (or a subclass such as :class:`NotFoundError`)
and the registered handlers translate it — and framework validation errors — into
that envelope with the correct HTTP status code (spec §4: 404 for unknown UUIDs,
422 for invalid input).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.observability.logging import get_logger

_logger = get_logger("api.error")


class APIError(Exception):
    """Base class for errors that map to a specific HTTP status + envelope."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}


class NotFoundError(APIError):
    """A requested resource (profile, query, ...) does not exist → HTTP 404."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the uniform error body."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def install_error_handlers(app: FastAPI) -> None:
    """Register the exception handlers on the FastAPI app."""

    @app.exception_handler(APIError)
    async def _handle_api_error(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_envelope(
                "validation_error",
                "Request validation failed.",
                {"errors": exc.errors()},
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Last-resort guard: never leak a stack trace, always return the envelope.
        _logger.error("api.unhandled_exception", error=type(exc).__name__, message=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("internal_error", "An unexpected error occurred."),
        )


__all__ = ["APIError", "NotFoundError", "install_error_handlers"]
