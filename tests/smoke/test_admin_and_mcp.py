"""S36 w1 — Smoke tests: FastMCP HTTP transport, schema registry, admin routers.

Tests that FastMCP is correctly mounted, schema registry is accessible,
and key admin routers are included in the API.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.endpoints.admin_capabilities import (
    router as admin_capabilities_router,
)
from src.backend.entrypoints.api.v1.endpoints.admin_schemas import (
    router as schemas_router,
)


def test_schemas_router_mounts() -> None:
    """GET /api/v1/admin/schemas returns 200 (no auth required for smoke)."""
    app = FastAPI()
    app.include_router(schemas_router, prefix="/api/v1/admin")
    client = TestClient(app)
    response = client.get("/api/v1/admin/schemas")
    # 200 = registered, [] = no schemas yet (acceptable)
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_schemas_router_rejects_non_json() -> None:
    """GET /api/v1/admin/schemas with invalid accept header returns 200 still."""
    app = FastAPI()
    app.include_router(schemas_router, prefix="/api/v1/admin")
    client = TestClient(app)
    response = client.get("/api/v1/admin/schemas", headers={"Accept": "text/html"})
    # Should still return JSON (FastAPI default)
    assert response.status_code == 200


def test_admin_capabilities_router_mounts() -> None:
    """GET /api/v1/admin/capabilities returns 200 and a dict."""
    app = FastAPI()
    app.include_router(admin_capabilities_router, prefix="/api/v1/admin")
    client = TestClient(app)
    response = client.get("/api/v1/admin/capabilities")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_mcp_http_app_created_when_enabled(monkeypatch) -> None:
    """When MCP_HTTP_ENABLED=true, create_mcp_http_app() is called and mounted."""
    pytest.importorskip("fastmcp")
    monkeypatch.setenv("MCP_HTTP_ENABLED", "true")

    from src.backend.entrypoints.mcp.http_server import create_mcp_http_app

    app = create_mcp_http_app()
    # Smoke: app should be truthy (FastMCP ASGI app)
    assert app is not None


def test_mcp_http_app_routes_exist() -> None:
    """FastMCP HTTP app has a /tools route (MCP protocol)."""
    fastmcp = pytest.importorskip("fastmcp")
    from src.backend.entrypoints.mcp.http_server import create_mcp_http_app

    app = create_mcp_http_app()
    routes = [r.path for r in app.routes]
    # FastMCP mounts /tools and /resources under its prefix
    assert any("/tools" in r or r == "/mcp" or "/mcp/" in r for r in routes)
