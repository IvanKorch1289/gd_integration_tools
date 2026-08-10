"""Unit tests for small middleware modules."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.auth_method_header import (
    AuthMethodHeaderMiddleware,
)
from src.backend.entrypoints.middlewares.blocked_routes import BlockedRoutesMiddleware
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
    # Cycle 39: pure ASGI — 403 отправляется напрямую через send,
    # НЕ raise (в pure ASGI exceptions не обрабатываются автоматически).
    from src.backend.core.state.runtime import blocked_routes

    async def downstream(scope, receive, send):
        raise AssertionError("downstream должен быть skipped для blocked path")

    app = AsyncMock()
    app.side_effect = downstream
    mw = BlockedRoutesMiddleware(app)

    blocked_routes.add("/blocked")
    try:
        send = AsyncMock()
        await mw(
            {"type": "http", "method": "GET", "path": "/blocked", "headers": []},
            AsyncMock(),
            send,
        )

        start_msg = next(
            c.args[0] for c in send.await_args_list
            if c.args[0]["type"] == "http.response.start"
        )
        assert start_msg["status"] == 403
        body_msg = next(
            c.args[0] for c in send.await_args_list
            if c.args[0]["type"] == "http.response.body"
        )
        import json

        body = json.loads(body_msg["body"].decode("utf-8"))
        assert "detail" in body
    finally:
        blocked_routes.discard("/blocked")


@pytest.mark.asyncio
async def test_blocked_routes_allowed() -> None:
    # Cycle 39: pure ASGI — allowed path пробрасывается downstream.
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = AsyncMock()
    app.side_effect = downstream
    mw = BlockedRoutesMiddleware(app)
    send = AsyncMock()
    await mw(
        {"type": "http", "method": "GET", "path": "/allowed", "headers": []},
        AsyncMock(),
        send,
    )

    start_msg = next(
        c.args[0] for c in send.await_args_list
        if c.args[0]["type"] == "http.response.start"
    )
    assert start_msg["status"] == 200


@pytest.mark.asyncio
async def test_blocked_routes_glob_pattern() -> None:
    # Cycle 39: pure ASGI — glob matching с ``*``.
    from src.backend.core.state.runtime import blocked_routes

    async def downstream(scope, receive, send):
        raise AssertionError("downstream должен быть skipped для glob-matched path")

    app = AsyncMock()
    app.side_effect = downstream
    mw = BlockedRoutesMiddleware(app)

    blocked_routes.add("/api/v1/admin/*")
    try:
        send = AsyncMock()
        await mw(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/admin/users",
                "headers": [],
            },
            AsyncMock(),
            send,
        )

        start_msg = next(
            c.args[0] for c in send.await_args_list
            if c.args[0]["type"] == "http.response.start"
        )
        assert start_msg["status"] == 403
    finally:
        blocked_routes.discard("/api/v1/admin/*")


# ─── Test block (cycle 39): was below, now removed (stale duplicate)


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
