"""Тесты admin cache metrics endpoint (CACHE-3)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.endpoints.admin import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/admin")
    return app


def test_cache_stats_endpoint_returns_metrics() -> None:
    """GET /admin/cache/stats возвращает метрики из всех tier'ов."""
    app = _make_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/cache/stats")
        assert response.status_code == 200
        data = response.json()
        # Check that all expected metrics are present
        assert "lru_cache_hits" in data
        assert "lru_cache_misses" in data
        assert "rag_hits" in data
        assert "rag_misses" in data
        assert "semantic_tier_hits" in data
        assert "total_lru_hits" in data
        assert "total_lru_misses" in data
        assert "total_rag_hits" in data
        assert "total_rag_misses" in data


def test_cache_stats_returns_zeros_when_no_cache_used() -> None:
    """Метрики возвращают 0 если кэш не использовался."""
    app = _make_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/cache/stats")
        assert response.status_code == 200
        data = response.json()
        # All values should be integers
        assert isinstance(data["lru_cache_hits"], int)
        assert isinstance(data["lru_cache_misses"], int)
        assert isinstance(data["semantic_tier_hits"], int)
