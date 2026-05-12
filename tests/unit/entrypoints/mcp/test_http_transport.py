"""Тесты FastMCP HTTP transport + auth middleware (Wave D.4)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_auth_middleware_rejects_without_credentials() -> None:
    from src.backend.entrypoints.mcp.auth_middleware import McpAuthMiddleware

    async def _app(scope, receive, send):  # noqa: ANN001
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    sent: list[dict] = []

    async def _send(message: dict) -> None:
        sent.append(message)

    async def _receive() -> dict:
        return {"type": "http.request", "body": b""}

    middleware = McpAuthMiddleware(_app)
    scope = {"type": "http", "headers": [], "method": "GET", "path": "/mcp"}
    await middleware(scope, _receive, _send)
    statuses = [m["status"] for m in sent if m["type"] == "http.response.start"]
    assert 401 in statuses


@pytest.mark.asyncio
async def test_auth_middleware_passes_with_api_key() -> None:
    from src.backend.entrypoints.mcp import auth_middleware as auth_mod

    async def _passthrough(scope, receive, send):  # noqa: ANN001
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    sent: list[dict] = []

    async def _send(message: dict) -> None:
        sent.append(message)

    async def _receive() -> dict:
        return {"type": "http.request", "body": b""}

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/mcp",
        "headers": [(b"x-api-key", b"valid-key")],
    }

    fake_ctx = type("Ctx", (), {})()

    with patch(
        "src.backend.entrypoints.api.dependencies.auth_selector._verify_api_key",
        AsyncMock(return_value=fake_ctx),
    ), patch(
        "src.backend.entrypoints.api.dependencies.auth_selector._verify_jwt",
        AsyncMock(return_value=None),
    ):
        middleware = auth_mod.McpAuthMiddleware(_passthrough)
        await middleware(scope, _receive, _send)

    statuses = [m["status"] for m in sent if m["type"] == "http.response.start"]
    assert 200 in statuses


@pytest.mark.asyncio
async def test_auth_middleware_passes_through_non_http() -> None:
    from src.backend.entrypoints.mcp.auth_middleware import McpAuthMiddleware

    called: dict[str, Any] = {"hit": False}

    async def _app(scope, receive, send):  # noqa: ANN001
        called["hit"] = True

    middleware = McpAuthMiddleware(_app)
    await middleware(
        {"type": "lifespan"}, AsyncMock(return_value={}), AsyncMock(return_value=None)
    )
    assert called["hit"] is True


def test_resolve_http_app_prefers_modern_methods() -> None:
    from src.backend.entrypoints.mcp.http_server import _resolve_http_app

    class _FakeMcp:
        def http_app(self):  # noqa: ANN001
            return object()

    assert _resolve_http_app(_FakeMcp()) is not None


def test_resolve_http_app_falls_back_to_sse() -> None:
    from src.backend.entrypoints.mcp.http_server import _resolve_http_app

    class _Legacy:
        def sse_app(self):  # noqa: ANN001
            return object()

    assert _resolve_http_app(_Legacy()) is not None
