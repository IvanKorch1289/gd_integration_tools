"""S36 w1 — Smoke tests: Kubernetes health probes.

Tests that /liveness, /readiness, /startup, /components endpoints
are correctly mounted and return expected response shapes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.endpoints.health import router as health_router


def _make_minimal_app() -> FastAPI:
    """Minimal FastAPI app with health router mounted, no full startup."""
    app = FastAPI()
    app.state.infrastructure_ready = True
    app.include_router(health_router, prefix="/health")
    return app


def test_liveness_returns_200_and_correct_shape() -> None:
    """GET /health/liveness → 200 + {status: 'alive', timestamp: ...}."""
    client = TestClient(_make_minimal_app())
    response = client.get("/health/liveness")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"
    assert "timestamp" in data


def test_liveness_cache_control_no_store() -> None:
    """Liveness probe must have Cache-Control: no-store."""
    client = TestClient(_make_minimal_app())
    response = client.get("/health/liveness")
    assert response.status_code == 200
    assert "no-store" in response.headers.get("Cache-Control", "")


def test_readiness_returns_503_when_not_ready() -> None:
    """Readiness returns 503 when infrastructure_ready=False."""
    app = FastAPI()
    app.state.infrastructure_ready = False
    app.include_router(health_router, prefix="/health")
    client = TestClient(app)
    response = client.get("/health/readiness")
    assert response.status_code == 503
    assert response.json()["status"] == "initializing"


def test_readiness_returns_200_when_ready() -> None:
    """Readiness returns 200 when infrastructure_ready=True and no down components."""
    app = FastAPI()
    app.state.infrastructure_ready = True

    mock_provider = MagicMock()
    mock_provider.status.return_value = {}
    app.state._mock_resilience_provider = mock_provider

    def mock_status():
        return {}

    # Patch at import-time provider lookup
    import src.backend.core.di.providers as di_providers

    original = di_providers.get_resilience_coordinator_provider
    di_providers.get_resilience_coordinator_provider = lambda: mock_provider

    app.include_router(health_router, prefix="/health")
    client = TestClient(app)
    response = client.get("/health/readiness")

    di_providers.get_resilience_coordinator_provider = original

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["degraded"] is False


def test_readiness_returns_503_when_component_down() -> None:
    """Readiness returns 503 when any component status is 'down'."""
    from dataclasses import dataclass

    @dataclass
    class MockComponent:
        degradation: str = "down"

    app = FastAPI()
    app.state.infrastructure_ready = True

    mock_provider = MagicMock()
    mock_provider.status.return_value = {"redis": MockComponent(degradation="down")}

    import src.backend.core.di.providers as di_providers

    original = di_providers.get_resilience_coordinator_provider
    di_providers.get_resilience_coordinator_provider = lambda: mock_provider

    app.include_router(health_router, prefix="/health")
    client = TestClient(app)
    response = client.get("/health/readiness")

    di_providers.get_resilience_coordinator_provider = original

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert "redis" in data["down_components"]


def test_startup_returns_503_when_not_ready() -> None:
    """Startup probe returns 503 when infrastructure_ready=False."""
    app = FastAPI()
    app.state.infrastructure_ready = False
    app.include_router(health_router, prefix="/health")
    client = TestClient(app)
    response = client.get("/health/startup")
    assert response.status_code == 503
    assert response.json()["status"] == "starting"


def test_components_invalid_mode_returns_400() -> None:
    """GET /health/components?mode=invalid → 400."""
    client = TestClient(_make_minimal_app())
    response = client.get("/health/components?mode=invalid")
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == "error"
    assert "invalid mode" in data["error"]


def test_components_fast_mode_returns_200() -> None:
    """GET /health/components?mode=fast → 200 with status field."""
    app = FastAPI()

    mock_aggregator = MagicMock(spec=["check_all"])
    mock_report = {"status": "ok", "components": {}}
    mock_aggregator.check_all = AsyncMock(return_value=mock_report)

    import src.backend.core.di.providers as di_providers

    original_agg = di_providers.get_health_aggregator_provider
    original_res = di_providers.get_resilience_components_report_provider
    original_check = mock_aggregator.check_all

    try:
        di_providers.get_health_aggregator_provider = lambda: mock_aggregator
        di_providers.get_resilience_components_report_provider = lambda: MagicMock(
            return_value={"chains": []}
        )

        app.include_router(health_router, prefix="/health")
        client = TestClient(app)
        response = client.get("/health/components?mode=fast")

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.json()}"
        )
        data = response.json()
        assert "status" in data
    finally:
        di_providers.get_health_aggregator_provider = original_agg
        di_providers.get_resilience_components_report_provider = original_res


def test_components_deep_mode_includes_resilience_chains() -> None:
    """GET /health/components?mode=deep → 200 with resilience_chains."""
    app = FastAPI()

    mock_aggregator = MagicMock(spec=["check_all"])
    mock_aggregator.check_all = AsyncMock(
        return_value={"status": "ok", "components": {}}
    )

    mock_resilience_report = MagicMock(return_value={"chains": []})

    import src.backend.core.di.providers as di_providers

    original_agg = di_providers.get_health_aggregator_provider
    original_res = di_providers.get_resilience_components_report_provider

    try:
        di_providers.get_health_aggregator_provider = lambda: mock_aggregator
        di_providers.get_resilience_components_report_provider = lambda: (
            mock_resilience_report
        )

        app.include_router(health_router, prefix="/health")
        client = TestClient(app)
        response = client.get("/health/components?mode=deep")

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.json()}"
        )
        data = response.json()
        assert "resilience_chains" in data
    finally:
        di_providers.get_health_aggregator_provider = original_agg
        di_providers.get_resilience_components_report_provider = original_res
