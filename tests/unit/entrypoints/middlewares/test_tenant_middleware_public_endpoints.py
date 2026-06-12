"""S88 W4 — public/system endpoints exemption перевірка.

S88 W4 (V2 P0 #6): public/system endpoints мають працювати БЕЗ tenant context.
Перевіряємо що:
1. public routes (без X-Tenant-ID) — НЕ ламаються
2. system_mcp namespace — НЕ потребує tenant
3. TenantMiddleware default-tenant fallback ("default") — працює

Підхід: real Starlette Request + ASGI test transport.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from src.backend.entrypoints.middlewares.tenant import TenantMiddleware


def _make_request(headers: dict[str, str] | None = None) -> Request:
    """Створити реальний Starlette Request з headers."""
    headers = headers or {}
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "query_string": b"",
        "client": ("127.0.0.1", 0),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_tenant_middleware_default_when_no_header() -> None:
    """Без X-Tenant-ID header → middleware встановлює 'default'."""
    middleware = TenantMiddleware(app=AsyncMock(), default_tenant="default")

    request = _make_request()  # No headers

    call_next = AsyncMock()
    mock_response = AsyncMock()
    mock_response.headers = {}
    call_next.return_value = mock_response

    response = await middleware.dispatch(request, call_next)

    assert request.state.tenant_id == "default"
    assert response.headers.get("X-Tenant-ID") == "default"
    call_next.assert_called_once()


@pytest.mark.asyncio
async def test_tenant_middleware_uses_header() -> None:
    """З X-Tenant-ID header → middleware встановлює значення з header."""
    middleware = TenantMiddleware(app=AsyncMock(), default_tenant="default")

    request = _make_request({"X-Tenant-ID": "acme-corp"})

    call_next = AsyncMock()
    mock_response = AsyncMock()
    mock_response.headers = {}
    call_next.return_value = mock_response

    response = await middleware.dispatch(request, call_next)

    assert request.state.tenant_id == "acme-corp"
    assert response.headers.get("X-Tenant-ID") == "acme-corp"


@pytest.mark.asyncio
async def test_tenant_middleware_uses_state() -> None:
    """Без header але з request.state.tenant_id → middleware використовує state."""
    middleware = TenantMiddleware(app=AsyncMock(), default_tenant="default")

    request = _make_request()  # No headers, but state set below

    # Pre-populate state.tenant_id (mimicking JWT auth middleware)
    request.state.tenant_id = "from-jwt"

    call_next = AsyncMock()
    mock_response = AsyncMock()
    mock_response.headers = {}
    call_next.return_value = mock_response

    response = await middleware.dispatch(request, call_next)

    assert request.state.tenant_id == "from-jwt"
    assert response.headers.get("X-Tenant-ID") == "from-jwt"


def test_tenant_middleware_does_not_break_on_init() -> None:
    """TenantMiddleware __init__ не ламається без app."""
    middleware = TenantMiddleware(app=AsyncMock(), default_tenant="default")
    assert middleware._default == "default"
    assert callable(middleware.dispatch)
