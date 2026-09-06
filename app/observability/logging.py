"""Structured JSON logging with secret redaction.

Configures structlog to emit one JSON object per line to stdout. Two guarantees
matter for this system:

1. **Correlation:** ``correlation_id`` (bound via :mod:`app.observability.tracing`)
   is merged into every event automatically, so a run can be followed node-by-node.
2. **Redaction:** a processor scrubs sensitive values (API keys, passwords, auth
   headers, tokens) from every event *before* rendering, so secrets never reach
   the logs — even if a caller accidentally passes one.

Use :func:`configure_logging` once at startup and :func:`get_logger` everywhere.
:func:`log_node_event` is a small helper for the uniform per-node log records the
graph layer emits (event, node, duration_ms, success, retry_count, summaries).
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

# Sensitive markers are matched against *whole word segments* of a key (after
# splitting on separators and camelCase), not raw substrings. This deliberately
# avoids false positives like redacting ``total_tokens`` (count, not a secret) or
# ``author`` (contains "auth"), while still catching ``access_token``,
# ``dataforseo_login``, ``authorization``, etc.
_SENSITIVE_WORDS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "auth",
        "authorization",
        "credential",
        "credentials",
        "bearer",
        "login",
    }
)

# Matched against the separator-stripped key (e.g. ``api_key`` -> ``apikey``).
_SENSITIVE_COMPOUND: tuple[str, ...] = ("apikey",)

_SEGMENT_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

_REDACTED = "***REDACTED***"

_configured = False


def _segments(key: str) -> list[str]:
    """Split a key into lowercase word segments (handles snake_case + camelCase)."""
    words: list[str] = []
    for part in re.split(r"[^a-zA-Z0-9]+", key):
        words.extend(_SEGMENT_RE.findall(part))
    return [w.lower() for w in words if w]


def _is_sensitive(key: str) -> bool:
    """True when a mapping key looks like it holds a secret."""
    segments = _segments(key)
    if any(segment in _SENSITIVE_WORDS for segment in segments):
        return True
    joined = "".join(segments)
    return any(compound in joined for compound in _SENSITIVE_COMPOUND)


def _redact_value(value: Any) -> Any:
    """Recursively redact sensitive entries inside dicts/lists."""
    if isinstance(value, dict):
        return {k: (_REDACTED if _is_sensitive(k) else _redact_value(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


def redact_processor(
    _logger: Any, _method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """structlog processor: redact sensitive keys anywhere in the event dict."""
    redacted: dict[str, Any] = {}
    for key, value in event_dict.items():
        if _is_sensitive(key):
            redacted[key] = _REDACTED
        else:
            redacted[key] = _redact_value(value)
    return redacted


def configure_logging(level: str = "INFO", *, json_logs: bool = True) -> None:
    """Configure structlog + stdlib logging once for the process.

    Args:
        level: Minimum log level (e.g. ``"INFO"``, ``"DEBUG"``).
        json_logs: Emit JSON (production/default). When ``False``, use a colorized
            console renderer for local readability.
    """
    global _configured

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
        force=True,
    )

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # inject correlation_id, etc.
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_processor,  # scrub secrets before rendering
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger, configuring logging on first use."""
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)


def log_node_event(
    logger: structlog.stdlib.BoundLogger,
    *,
    node: str,
    success: bool,
    duration_ms: float,
    retry_count: int = 0,
    input_summary: dict[str, Any] | None = None,
    output_summary: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> None:
    """Emit the uniform ``node.finish`` record used by the graph layer.

    ``input_summary``/``output_summary`` are compact summaries (never raw payloads)
    and are passed through the redaction processor as a safety net.
    """
    event = "node.finish" if success else "node.error"
    logger.info(
        event,
        node=node,
        success=success,
        duration_ms=duration_ms,
        retry_count=retry_count,
        input_summary=input_summary or {},
        output_summary=output_summary or {},
        error_code=error_code,
    )
