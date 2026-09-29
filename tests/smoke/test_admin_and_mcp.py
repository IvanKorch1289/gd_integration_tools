"""S36 w1 — Smoke tests: FastMCP HTTP transport, schema registry, admin routers.

Tests that FastMCP is correctly mounted, schema registry is accessible,
and key admin routers are included in the API.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.auth.admin_roles import AdminRole
from src.backend.entrypoints.api.v1.endpoints.admin_capabilities import (
    router as admin_capabilities_router,
)
from src.backend.entrypoints.api.v1.endpoints.admin_schemas import (
    router as schemas_router,
)

# S202 audit fix добавил к admin-роутерам ``dependencies=[Depends(require_admin(...))]``.
# Раньше эти smoke-тесты строили голый FastAPI() без auth-middleware и ждали 200;
# теперь guard честно fail-closed отдаёт 403. Тесты обновлены под текущий контракт:
# аутентифицированный запрос проходит, неаутентифицированный — отклоняется.
# Ослаблять guard нельзя: это защита admin-endpoints.


def _build_app(router, *, auth: bool) -> FastAPI:
    """Собрать приложение с роутером; при auth=True — контекст SUPER_ADMIN."""
    app = FastAPI()
    if auth:
        ctx = AuthContext(
            method=AuthMethod.API_KEY,
            principal="smoke-admin",
            metadata={"admin_roles": [AdminRole.SUPER_ADMIN.value]},
        )

        @app.middleware("http")
        async def _inject_auth(request, call_next):  # type: ignore[no-untyped-def]
            # Тот же канал, что использует AuthRequiredMiddleware в проде:
            # require_admin читает request.state.auth.
            request.state.auth = ctx
            return await call_next(request)

    app.include_router(router, prefix="/api/v1/admin")
    return app


def test_schemas_router_mounts() -> None:
    """GET /api/v1/admin/schemas returns 200 для admin-роли."""
    client = TestClient(_build_app(schemas_router, auth=True))
    response = client.get("/api/v1/admin/schemas")
    # 200 = registered, {} = no schemas yet (acceptable)
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_schemas_router_rejects_non_json() -> None:
    """GET /api/v1/admin/schemas with invalid accept header returns 200 still."""
    client = TestClient(_build_app(schemas_router, auth=True))
    response = client.get("/api/v1/admin/schemas", headers={"Accept": "text/html"})
    # Should still return JSON (FastAPI default)
    assert response.status_code == 200


def test_admin_capabilities_router_mounts() -> None:
    """GET /api/v1/admin/capabilities returns 200 and a dict."""
    client = TestClient(_build_app(admin_capabilities_router, auth=True))
    response = client.get("/api/v1/admin/capabilities")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_admin_schemas_rejects_unauthenticated() -> None:
    """S202: без admin-контекста admin-endpoint обязан fail-closed (403)."""
    client = TestClient(_build_app(schemas_router, auth=False))
    assert client.get("/api/v1/admin/schemas").status_code == 403


def test_admin_capabilities_rejects_unauthenticated() -> None:
    """S202: capabilities-endpoint также закрыт от неаутентифицированных."""
    client = TestClient(_build_app(admin_capabilities_router, auth=False))
    assert client.get("/api/v1/admin/capabilities").status_code == 403


def test_mcp_http_app_created_when_enabled(monkeypatch) -> None:
    """When MCP_HTTP_ENABLED=true, create_mcp_http_app() is called and mounted."""
    pytest.importorskip("fastmcp")
    monkeypatch.setenv("MCP_HTTP_ENABLED", "true")

    from src.backend.entrypoints.mcp.http_server import create_mcp_http_app

    app, _lifespan = create_mcp_http_app()
    # Smoke: app should be truthy (FastMCP ASGI app)
    assert app is not None


def test_mcp_http_app_routes_exist() -> None:
    """FastMCP HTTP app has a /tools route (MCP protocol)."""
    pytest.importorskip("fastmcp")
    from src.backend.entrypoints.mcp.http_server import create_mcp_http_app

    app, _lifespan = create_mcp_http_app()
    # S49 W1: create_mcp_http_app() возвращает McpAuthMiddleware, обёрнутый
    # вокруг ASGI-приложения FastMCP, а не сам FastAPI/Starlette app —
    # поэтому ``.routes`` есть только у внутреннего приложения.
    inner = getattr(app, "_app", app)
    routes = [getattr(r, "path", "") for r in inner.routes]
    # D-AUDIT-20812 (cycle 218): внутренний путь намеренно "/" — Starlette
    # Mount re-root'ит входящий запрос в "/", и внутренний route обязан
    # совпасть, иначе /mcp отдаёт 404. Ожидание "/tools" или "/mcp" было
    # написано до этого фикса и проверяло уже несуществующий контракт.
    assert "/" in routes, routes
