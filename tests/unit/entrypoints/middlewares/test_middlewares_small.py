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
    # Cycle 37: AuthMethodHeaderMiddleware — pure ASGI.
    app = AsyncMock()

    async def downstream(scope, receive, send):
        # Downstream выставляет auth context в scope['state'].
        scope["state"] = {
            "auth": type("AuthCtx", (), {"method": type("M", (), {"value": "jwt"})()})()
        }
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = AuthMethodHeaderMiddleware(app, enabled=True)
    send = AsyncMock()
    await mw({"type": "http", "method": "GET", "path": "/", "headers": []}, AsyncMock(), send)

    start_msg = next(
        c.args[0] for c in send.await_args_list if c.args[0]["type"] == "http.response.start"
    )
    headers = dict(start_msg["headers"])
    assert headers[b"x-auth-method"] == b"jwt"


@pytest.mark.asyncio
async def test_auth_method_header_no_auth() -> None:
    # Cycle 37: enabled=False default — НЕ emit'ит header (security).
    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = AuthMethodHeaderMiddleware(app)  # enabled=False default
    send = AsyncMock()
    await mw({"type": "http", "method": "GET", "path": "/", "headers": []}, AsyncMock(), send)

    start_msg = next(
        c.args[0] for c in send.await_args_list if c.args[0]["type"] == "http.response.start"
    )
    headers = dict(start_msg["headers"])
    assert b"x-auth-method" not in headers


# ─── BlockedRoutesMiddleware ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blocked_routes_blocked() -> None:
    # Cycle 114: production blocked_routes.py:35 now ``raise HTTPException(...)``
    # (was ``return JSONResponse(403)`` in S176, raised HTTPException from
    # subsequent refactor). Revert Cycle 80 fix to expect raise.
    from fastapi import HTTPException

    app = AsyncMock()
    mw = BlockedRoutesMiddleware(app)
    request = MagicMock()
    request.url.path = "/blocked"
    blocked_routes.add("/blocked")
    call_next = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await mw.dispatch(request, call_next)
    assert exc_info.value.status_code == 403
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
    from fastapi import HTTPException

    app = AsyncMock()
    mw = BlockedRoutesMiddleware(app)
    request = MagicMock()
    request.url.path = "/api/v1/admin/users"
    blocked_routes.add("/api/v1/admin/*")
    call_next = AsyncMock()
    try:
        # Cycle 114: production raises HTTPException.
        with pytest.raises(HTTPException) as exc_info:
            await mw.dispatch(request, call_next)
        assert exc_info.value.status_code == 403
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
    # Cycle 36: RequestIDMiddleware — pure ASGI (не BaseHTTPMiddleware).
    # Call via __call__(scope, receive, send) and inspect http.response.start.
    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = RequestIDMiddleware(app)
    send = AsyncMock()
    await mw(
        {"type": "http", "method": "GET", "path": "/", "headers": []},
        AsyncMock(),
        send,
    )

    # Find http.response.start message.
    start_msg = next(
        c.args[0] for c in send.await_args_list if c.args[0]["type"] == "http.response.start"
    )
    headers = dict(start_msg["headers"])
    assert b"x-request-id" in headers
    assert b"x-correlation-id" in headers
    assert len(headers[b"x-request-id"]) == 32  # uuid4 hex


@pytest.mark.asyncio
async def test_request_id_preserves_existing() -> None:
    # Cycle 36: incoming X-Request-ID / X-Correlation-ID пробрасываются.
    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = RequestIDMiddleware(app)
    send = AsyncMock()
    await mw(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (b"x-request-id", b"req-123"),
                (b"x-correlation-id", b"corr-456"),
            ],
        },
        AsyncMock(),
        send,
    )

    start_msg = next(
        c.args[0] for c in send.await_args_list if c.args[0]["type"] == "http.response.start"
    )
    headers = dict(start_msg["headers"])
    assert headers[b"x-request-id"] == b"req-123"
    assert headers[b"x-correlation-id"] == b"corr-456"


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
