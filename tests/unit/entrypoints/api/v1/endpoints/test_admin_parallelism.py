"""Unit tests for admin_parallelism endpoint (S13 K5 W3 / K2 W3)."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.endpoints import admin_parallelism as mod


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(mod.router, prefix="/api/v1")

    @app.middleware("http")
    async def _add_auth_context(request, call_next):
        from src.backend.core.auth import AuthContext, AuthMethod

        request.state.auth_context = AuthContext(
            method=AuthMethod.NONE,
            principal="test",
            metadata={"admin_roles": ["super_admin"]},
        )
        return await call_next(request)

    return app


def _fake_registry_module(route: Any | None = None) -> MagicMock:
    """Creates a fake module with route_registry for patching sys.modules."""
    fake_registry = MagicMock()
    fake_registry.get.return_value = route
    fake_module = MagicMock()
    fake_module.route_registry = fake_registry
    return fake_module


# ─── parallelism_report ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parallelism_report_with_registry() -> None:
    """parallelism_report returns analysis for existing route."""

    class FakeRoute:
        steps = [
            {"type": "a", "id": "step_0"},
            {"type": "b", "id": "step_1"},
            {"type": "c", "id": "step_2"},
        ]

    fake_module = _fake_registry_module(FakeRoute())

    with patch.dict(
        sys.modules, {"src.backend.dsl.route_loader.registry": fake_module}
    ):
        result = await mod.parallelism_report("test-route")

    assert result["route_id"] == "test-route"
    assert result["total_steps"] == 3
    assert isinstance(result["parallel_groups"], list)
    assert isinstance(result["critical_path"], list)
    assert isinstance(result["estimated_speedup"], float)
    assert isinstance(result["suggested_optimizations"], list)
    assert isinstance(result["dependencies"], list)


@pytest.mark.asyncio
async def test_parallelism_report_route_not_found() -> None:
    """parallelism_report raises 404 when route is not found."""
    fake_module = _fake_registry_module(None)

    with patch.dict(
        sys.modules, {"src.backend.dsl.route_loader.registry": fake_module}
    ):
        with pytest.raises(HTTPException) as exc_info:
            await mod.parallelism_report("missing")

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_parallelism_report_registry_import_error() -> None:
    """parallelism_report works when route_registry import fails."""
    with patch.dict(
        sys.modules, {"src.backend.dsl.route_loader.registry": None}, clear=False
    ):
        # Remove the module from sys.modules to force ImportError
        original = sys.modules.pop("src.backend.dsl.route_loader.registry", None)
        try:
            result = await mod.parallelism_report("any")
        finally:
            if original is not None:
                sys.modules["src.backend.dsl.route_loader.registry"] = original

    assert result["total_steps"] == 0
    assert result["parallel_groups"] == []
    assert result["critical_path"] == []
    assert result["estimated_speedup"] == 1.0
    assert result["suggested_optimizations"] == []
    assert result["dependencies"] == []


@pytest.mark.asyncio
async def test_parallelism_report_registry_exception() -> None:
    """parallelism_report handles exception from registry gracefully."""
    fake_registry = MagicMock()
    fake_registry.get.side_effect = RuntimeError("boom")
    fake_module = MagicMock()
    fake_module.route_registry = fake_registry

    with patch.dict(
        sys.modules, {"src.backend.dsl.route_loader.registry": fake_module}
    ):
        result = await mod.parallelism_report("any")

    assert result["total_steps"] == 0
    assert result["parallel_groups"] == []


# ─── HTTP integration ────────────────────────────────────────────────────────


def test_parallelism_report_http_200() -> None:
    """HTTP GET returns 200 with report data."""
    app = _make_app()

    class FakeRoute:
        steps = [{"type": "a", "id": "step_0"}]

    fake_module = _fake_registry_module(FakeRoute())

    with patch.dict(
        sys.modules, {"src.backend.dsl.route_loader.registry": fake_module}
    ):
        client = TestClient(app)
        resp = client.get("/api/v1/admin/routes/test-route/parallelism-report")

    assert resp.status_code == 200
    data = resp.json()
    assert data["route_id"] == "test-route"
    assert data["total_steps"] == 1


def test_parallelism_report_http_404() -> None:
    """HTTP GET returns 404 when route not found."""
    app = _make_app()
    fake_module = _fake_registry_module(None)

    with patch.dict(
        sys.modules, {"src.backend.dsl.route_loader.registry": fake_module}
    ):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/admin/routes/missing/parallelism-report")

    assert resp.status_code == 404
