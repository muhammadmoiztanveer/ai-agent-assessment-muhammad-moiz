"""Phase 0 smoke tests: the app boots and configuration is sane."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.config import Settings


def test_settings_defaults_are_valid() -> None:
    settings = Settings()
    assert settings.dataforseo_mode == "mock"
    # opportunity-score weights must sum to 1.0
    total = settings.opp_weight_volume + settings.opp_weight_difficulty + settings.opp_weight_gap
    assert abs(total - 1.0) < 1e-6


def test_health_endpoint() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "1.0.0"
