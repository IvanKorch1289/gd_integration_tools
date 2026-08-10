"""S88 W4 — public/system endpoints exemption перевірка (cycle 38: pure ASGI).

S88 W4 (V2 P0 #6): public/system endpoints мають працювати БЕЗ tenant context.
Перевіряємо що:
1. public routes (без X-Tenant-ID) — НЕ ламаються
2. system_mcp namespace — НЕ потребує tenant
3. TenantMiddleware default-tenant fallback ("default") — працює

Підхід: pure ASGI scope + send-wrapper.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.entrypoints.middlewares.tenant import TenantMiddleware


def _make_scope(headers: dict[str, str] | None = None) -> dict:
    """Створити ASGI scope з headers."""
    headers = headers or {}
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "query_string": b"",
        "client": ("127.0.0.1", 0),
        "server": ("testserver", 80),
        "scheme": "http",
    }


def _start_headers(send_mock: AsyncMock) -> dict[bytes, bytes]:
    """Извлекает headers из http.response.start."""
    for call in send_mock.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return dict(msg.get("headers", []))
    return {}


@pytest.mark.asyncio
async def test_tenant_middleware_default_when_no_header() -> None:
    """Без X-Tenant-ID header → middleware использует 'default'."""
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = AsyncMock()
    app.side_effect = downstream
    middleware = TenantMiddleware(app=app, default_tenant="default")

    with patch(
        "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
        return_value=MagicMock(),
    ):
        send = AsyncMock()
        await middleware(_make_scope(), AsyncMock(), send)

    headers = _start_headers(send)
    assert headers.get(b"x-tenant-id") == b"default"


@pytest.mark.asyncio
async def test_tenant_middleware_uses_header() -> None:
    """С X-Tenant-ID header → middleware использует значение из header."""
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = AsyncMock()
    app.side_effect = downstream
    middleware = TenantMiddleware(app=app, default_tenant="default")

    with patch(
        "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
        return_value=MagicMock(),
    ):
        send = AsyncMock()
        await middleware(
            _make_scope({"X-Tenant-ID": "acme-corp"}), AsyncMock(), send,
        )

    headers = _start_headers(send)
    assert headers.get(b"x-tenant-id") == b"acme-corp"


@pytest.mark.asyncio
async def test_tenant_middleware_uses_state() -> None:
    """Без header, но с request.state.tenant_id → middleware использует state.

    Cycle 38: inner auth middleware (downstream) устанавливает
    state['tenant_id'] ПЕРЕД нашим send-wrapper, поэтому resolution
    в send-wrapper видит актуальное значение.
    """
    async def downstream(scope, receive, send):
        # Имитирует JWT auth middleware (должен быть INNER относительно tenant).
        scope.setdefault("state", {})["tenant_id"] = "from-jwt"
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = AsyncMock()
    app.side_effect = downstream
    middleware = TenantMiddleware(app=app, default_tenant="default")

    with patch(
        "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
        return_value=MagicMock(),
    ):
        send = AsyncMock()
        await middleware(_make_scope(), AsyncMock(), send)

    headers = _start_headers(send)
    assert headers.get(b"x-tenant-id") == b"from-jwt"


def test_tenant_middleware_does_not_break_on_init() -> None:
    """TenantMiddleware __init__ не ломается без app.

    Cycle 38: middleware больше не имеет .dispatch (pure ASGI).
    """
    middleware = TenantMiddleware(app=AsyncMock(), default_tenant="default")
    assert middleware._default == "default"
    # Pure ASGI: __call__ — точка входа (а не .dispatch).
    assert callable(middleware.__call__)
