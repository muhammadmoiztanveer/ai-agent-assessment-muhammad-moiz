"""Phase 2 observability tests: redaction, correlation-id tracing, metrics."""

from __future__ import annotations

import json
import time

import structlog

from app.observability.logging import (
    configure_logging,
    get_logger,
    redact_processor,
)
from app.observability.metrics import RunMetrics
from app.observability.tracing import (
    correlation_context,
    get_correlation_id,
    new_correlation_id,
    timed_span,
)


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #
def test_redact_processor_scrubs_sensitive_keys() -> None:
    event = {
        "event": "call",
        "password": "hunter2",
        "api_key": "sk-secret",
        "authorization": "Basic abc",
        "keyword": "best crm",  # not sensitive
        "nested": {"dataforseo_password": "pw", "location_code": 2840},
        "headers": [{"token": "t"}],
    }
    out = redact_processor(None, "info", dict(event))

    assert out["password"] == "***REDACTED***"
    assert out["api_key"] == "***REDACTED***"
    assert out["authorization"] == "***REDACTED***"
    assert out["keyword"] == "best crm"
    assert out["nested"]["dataforseo_password"] == "***REDACTED***"
    assert out["nested"]["location_code"] == 2840
    assert out["headers"][0]["token"] == "***REDACTED***"


def test_redaction_does_not_over_redact_safe_keys() -> None:
    """Legitimate keys that merely contain a sensitive substring must survive."""
    event = {
        "total_tokens": 200,  # contains "token" but is a count, not a secret
        "retry_count": 3,
        "api_calls": 5,
        "author": "jane",  # contains "auth"
        "authority": "high",
        "access_token": "sk-xyz",  # genuinely sensitive
        "openai_api_key": "sk-abc",  # genuinely sensitive
    }
    out = redact_processor(None, "info", dict(event))

    assert out["total_tokens"] == 200
    assert out["retry_count"] == 3
    assert out["api_calls"] == 5
    assert out["author"] == "jane"
    assert out["authority"] == "high"
    assert out["access_token"] == "***REDACTED***"
    assert out["openai_api_key"] == "***REDACTED***"


def test_secrets_never_reach_rendered_json_log(capsys) -> None:
    configure_logging(level="INFO", json_logs=True)
    logger = get_logger("test")
    logger.info("auth.attempt", password="hunter2", dataforseo_login="me@example.com", ok=True)

    captured = capsys.readouterr().out.strip().splitlines()
    assert captured, "expected at least one log line"
    record = json.loads(captured[-1])

    assert record["event"] == "auth.attempt"
    assert record["ok"] is True
    assert record["password"] == "***REDACTED***"
    assert record["dataforseo_login"] == "***REDACTED***"
    # the raw secret must appear nowhere in the serialized line
    assert "hunter2" not in captured[-1]
    assert "me@example.com" not in captured[-1]


# --------------------------------------------------------------------------- #
# Tracing
# --------------------------------------------------------------------------- #
def test_correlation_context_binds_and_restores() -> None:
    assert get_correlation_id() is None

    with correlation_context() as cid:
        assert cid
        assert get_correlation_id() == cid

    # context restored after exit
    assert get_correlation_id() is None


def test_correlation_context_reuses_supplied_id() -> None:
    fixed = new_correlation_id()
    with correlation_context(fixed) as cid:
        assert cid == fixed


def test_correlation_id_appears_on_every_log_line(capsys) -> None:
    configure_logging(level="INFO", json_logs=True)
    logger = get_logger("test")

    with correlation_context() as cid:
        logger.info("node.start", node="plan")
        logger.info("node.finish", node="plan")

    lines = [ln for ln in capsys.readouterr().out.strip().splitlines() if ln]
    records = [json.loads(ln) for ln in lines]
    relevant = [r for r in records if r.get("node") == "plan"]
    assert len(relevant) == 2
    assert all(r["correlation_id"] == cid for r in relevant)


def test_timed_span_records_duration() -> None:
    with timed_span("work") as span:
        time.sleep(0.01)
    assert span["name"] == "work"
    assert isinstance(span["duration_ms"], float)
    assert span["duration_ms"] >= 10.0


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def test_run_metrics_aggregation() -> None:
    m = RunMetrics(correlation_id="corr-abc")
    m.record_node(node="plan", duration_ms=12.0, success=True, api_calls=0)
    m.record_node(node="retrieve", duration_ms=80.0, success=True, retry_count=2, api_calls=3)
    m.record_node(node="normalize", duration_ms=5.0, success=False, error_code="empty_input")
    m.add_tokens(150)
    m.add_tokens(50)
    m.finish()

    summary = m.summary()
    assert summary["correlation_id"] == "corr-abc"
    assert summary["node_count"] == 3
    assert summary["success_count"] == 2
    assert summary["failure_count"] == 1
    assert summary["success_rate"] == 0.6667
    assert summary["total_api_calls"] == 3
    assert summary["total_retries"] == 2
    assert summary["total_tokens"] == 200
    assert summary["total_duration_ms"] >= 0.0
    assert len(summary["nodes"]) == 3
    assert summary["nodes"][2]["error_code"] == "empty_input"


def test_run_metrics_empty_success_rate() -> None:
    m = RunMetrics(correlation_id="c")
    assert m.success_rate == 0.0
    assert m.summary()["node_count"] == 0


def test_log_summary_emits_structured_event(capsys) -> None:
    configure_logging(level="INFO", json_logs=True)
    m = RunMetrics(correlation_id="corr-xyz")
    m.record_node(node="plan", duration_ms=1.0, success=True)
    m.add_tokens(200)
    m.finish()
    returned = m.log_summary()

    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "run.metrics"
    assert record["correlation_id"] == "corr-xyz"
    # total_tokens is a count, not a secret — it must NOT be redacted
    assert record["total_tokens"] == 200
    assert returned["node_count"] == 1


# --------------------------------------------------------------------------- #
# Teardown safety: reset structlog contextvars between tests
# --------------------------------------------------------------------------- #
def teardown_function() -> None:
    structlog.contextvars.clear_contextvars()
