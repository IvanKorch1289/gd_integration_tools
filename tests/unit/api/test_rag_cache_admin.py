"""Тесты admin-роутера RAG cache (К4 MVP, Шаг 7)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.endpoints.rag_cache_admin import (
    record_invalidation_event,
    router,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/admin")
    return app


def test_stats_returns_counters_and_enabled() -> None:
    app = _make_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/rag-cache/stats")
        assert response.status_code == 200
        data = response.json()
        assert "counters" in data
        assert "enabled" in data


def test_flush_invalid_tier_returns_400() -> None:
    app = _make_app()
    with TestClient(app) as client:
        response = client.post("/api/v1/admin/rag-cache/flush?tier=l9")
        assert response.status_code == 400


def test_flush_without_cache_registered_returns_503() -> None:
    app = _make_app()
    with TestClient(app) as client:
        response = client.post("/api/v1/admin/rag-cache/flush?tier=l1")
        assert response.status_code == 503


def test_events_endpoint_returns_recorded() -> None:
    record_invalidation_event({"tag": "orders"})
    app = _make_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/rag-cache/events?limit=10")
        assert response.status_code == 200
        events = response.json()
        assert any(e.get("tag") == "orders" for e in events)


def test_events_limit_parameter_validates() -> None:
    app = _make_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/rag-cache/events?limit=0")
        assert response.status_code == 422
