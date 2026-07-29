"""Unit tests for small middleware modules."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.backend.entrypoints.middlewares.auth_method_header import (
    AuthMethodHeaderMiddleware,
)
from src.backend.entrypoints.middlewares.blocked_routes import (
    BlockedRoutesMiddleware,
    blocked_routes,
)
from src.backend.entrypoints.middlewares.correlation import (
    CORRELATION_HEADER,
    CorrelationIdMiddleware,
)
from src.backend.entrypoints.middlewares.request_id import RequestIDMiddleware
from src.backend.entrypoints.middlewares.security_headers import (
    SecurityHeadersMiddleware,
)

# ─── AuthMethodHeaderMiddleware ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_method_header_with_method() -> None:
    app = AsyncMock()
    mw = AuthMethodHeaderMiddleware(app)
    request = MagicMock()
    request.state.auth = MagicMock()
    request.state.auth.method = MagicMock()
    request.state.auth.method.value = "jwt"
    response = Response(content=b"ok")
    call_next = AsyncMock(return_value=response)
    result = await mw.dispatch(request, call_next)
    assert result.headers["X-Auth-Method"] == "jwt"


@pytest.mark.asyncio
async def test_auth_method_header_no_auth() -> None:
    app = AsyncMock()
    mw = AuthMethodHeaderMiddleware(app)
    request = MagicMock()
    request.state.auth = None
    response = Response(content=b"ok")
    call_next = AsyncMock(return_value=response)
    result = await mw.dispatch(request, call_next)
    assert "X-Auth-Method" not in result.headers


# ─── BlockedRoutesMiddleware ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blocked_routes_blocked() -> None:
    # Cycle 80 L10 fix: middleware returns JSONResponse(403), does NOT
    # raise HTTPException. Previous test asserted raise HTTPException
    # which never happened.
    app = AsyncMock()
    mw = BlockedRoutesMiddleware(app)
    request = MagicMock()
    request.url.path = "/blocked"
    blocked_routes.add("/blocked")
    call_next = AsyncMock()
    response = await mw.dispatch(request, call_next)
    assert response.status_code == 403
    blocked_routes.discard("/blocked")


@pytest.mark.asyncio
async def test_blocked_routes_allowed() -> None:
    app = AsyncMock()
    mw = BlockedRoutesMiddleware(app)
    request = MagicMock()
    request.url.path = "/allowed"
    response = Response(content=b"ok")
    call_next = AsyncMock(return_value=response)
    result = await mw.dispatch(request, call_next)
    assert result is response


@pytest.mark.asyncio
async def test_blocked_routes_glob_pattern() -> None:
    app = AsyncMock()
    mw = BlockedRoutesMiddleware(app)
    request = MagicMock()
    request.url.path = "/api/v1/admin/users"
    blocked_routes.add("/api/v1/admin/*")
    call_next = AsyncMock()
    try:
        # Cycle 80 L10 fix: middleware returns JSONResponse(403), not raise.
        response = await mw.dispatch(request, call_next)
        assert response.status_code == 403
    finally:
        blocked_routes.discard("/api/v1/admin/*")


# ─── CorrelationIdMiddleware re-export ──────────────────────────────────────


def test_correlation_header_constant() -> None:
    assert CORRELATION_HEADER == "X-Correlation-ID"


def test_correlation_middleware_importable() -> None:
    assert CorrelationIdMiddleware is not None


# ─── RequestIDMiddleware ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_id_generates_ids() -> None:
    app = AsyncMock()
    mw = RequestIDMiddleware(app)
    request = Request(
        {"type": "http", "method": "GET", "url": "http://test/", "headers": []}
    )
    response = Response(content=b"ok")
    call_next = AsyncMock(return_value=response)
    result = await mw.dispatch(request, call_next)
    assert "X-Request-ID" in result.headers
    assert "X-Correlation-ID" in result.headers
    assert len(result.headers["X-Request-ID"]) == 32


@pytest.mark.asyncio
async def test_request_id_preserves_existing() -> None:
    app = AsyncMock()
    mw = RequestIDMiddleware(app)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "url": "http://test/",
            "headers": [
                (b"x-request-id", b"req-123"),
                (b"x-correlation-id", b"corr-456"),
            ],
        }
    )
    response = Response(content=b"ok")
    call_next = AsyncMock(return_value=response)
    result = await mw.dispatch(request, call_next)
    assert result.headers["X-Request-ID"] == "req-123"
    assert result.headers["X-Correlation-ID"] == "corr-456"


# ─── SecurityHeadersMiddleware ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_security_headers() -> None:
    # Cycle 79 L10: middleware is pure ASGI (not BaseHTTPMiddleware),
    # call via __call__(scope, receive, send) and inspect http.response.start.
    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = SecurityHeadersMiddleware(app)
    send = AsyncMock()
    await mw({"type": "http", "method": "GET", "path": "/", "headers": []}, AsyncMock(), send)
    captured = next(
        c.args[0] for c in send.await_args_list if c.args[0]["type"] == "http.response.start"
    )
    headers = dict(captured.get("headers", []))
    assert headers[b"x-frame-options"] == b"DENY"
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert b"strict-transport-security" in headers
