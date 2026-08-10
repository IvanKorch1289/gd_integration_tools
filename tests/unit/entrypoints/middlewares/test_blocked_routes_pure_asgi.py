"""Pure ASGI regression-тесты для BlockedRoutesMiddleware (cycle 39).

Middleware блокирует запросы к путям, совпадающим с glob-паттернами
в runtime_state ``blocked_routes``. Cycle 39: pure ASGI — 403
отправляется напрямую через ``send()`` (НЕ raise, как было в
BaseHTTPMiddleware версии).
"""


from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.blocked_routes import (
    BlockedRoutesMiddleware,
    blocked_routes,
)


def _start_message(send: AsyncMock) -> dict | None:
    """Извлекает http.response.start сообщение."""
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _body_message(send: AsyncMock) -> dict | None:
    """Извлекает http.response.body сообщение."""
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.body":
            return msg
    return None


@pytest.mark.asyncio
async def test_returns_403_for_blocked_path() -> None:
    """Blocked path → 403 JSON response напрямую через send."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        raise AssertionError("downstream должен быть skipped для blocked path")

    app.side_effect = downstream
    mw = BlockedRoutesMiddleware(app)

    blocked_routes.add("/api/v1/admin/*")
    try:
        send = AsyncMock()
        await mw(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/admin/users",
                "headers": [],
            },
            AsyncMock(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 403
        # Content-Type: application/json.
        headers = dict(start["headers"])
        assert headers[b"content-type"] == b"application/json"
        # Body — JSON с detail.
        body_msg = _body_message(send)
        assert body_msg is not None
        body = json.loads(body_msg["body"].decode("utf-8"))
        assert "detail" in body
    finally:
        blocked_routes.discard("/api/v1/admin/*")


@pytest.mark.asyncio
async def test_passes_through_allowed_path() -> None:
    """Allowed path → downstream отрабатывает, status=200."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = BlockedRoutesMiddleware(app)
    send = AsyncMock()
    await mw(
        {"type": "http", "method": "GET", "path": "/api/v1/users", "headers": []},
        AsyncMock(),
        send,
    )

    start = _start_message(send)
    assert start is not None
    assert start["status"] == 200


@pytest.mark.asyncio
async def test_glob_pattern_matches_nested_path() -> None:
    """Glob pattern ``/api/v1/admin/*`` блокирует любой nested path."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        raise AssertionError("downstream должен быть skipped")

    app.side_effect = downstream
    mw = BlockedRoutesMiddleware(app)

    blocked_routes.add("/api/v1/admin/*")
    try:
        send = AsyncMock()
        # Deeply nested path — должен блокироваться через glob.
        await mw(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/admin/users/123/groups",
                "headers": [],
            },
            AsyncMock(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 403
    finally:
        blocked_routes.discard("/api/v1/admin/*")


@pytest.mark.asyncio
async def test_exact_pattern_no_glob() -> None:
    """Exact pattern (без ``*``) блокирует только точное совпадение."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = BlockedRoutesMiddleware(app)

    blocked_routes.add("/health")
    try:
        send = AsyncMock()
        # /health/bypass — НЕ должен блокироваться (exact match only).
        await mw(
            {"type": "http", "method": "GET", "path": "/health/bypass", "headers": []},
            AsyncMock(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200  # Пропущен (downstream).
    finally:
        blocked_routes.discard("/health")


@pytest.mark.asyncio
async def test_passes_through_non_http_scope() -> None:
    """Non-HTTP scope (websocket) пробрасывается без проверки blocked_routes."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "websocket.accept"})

    app.side_effect = downstream
    mw = BlockedRoutesMiddleware(app)
    send = AsyncMock()
    await mw(
        {"type": "websocket", "path": "/ws", "headers": []},
        AsyncMock(),
        send,
    )

    # websocket.accept прошёл без 403.
    msg = send.await_args.args[0]
    assert msg["type"] == "websocket.accept"


@pytest.mark.asyncio
async def test_does_not_call_downstream_when_blocked() -> None:
    """Cycle 39 critical: при blocked path downstream НЕ вызывается."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        raise AssertionError("downstream НЕ должен быть вызван")

    app.side_effect = downstream
    mw = BlockedRoutesMiddleware(app)

    blocked_routes.add("/blocked-endpoint")
    try:
        send = AsyncMock()
        await mw(
            {"type": "http", "method": "GET", "path": "/blocked-endpoint", "headers": []},
            AsyncMock(),
            send,
        )

        # 403 был отправлен (от нашего send), но downstream НЕ был вызван
        # (AssertionError внутри downstream не возник — значит он не вызывался).
        # Если бы downstream был вызван, AssertionError пробросился бы наружу.
        # Это и есть assert — тест прошёл = downstream не вызывался.
    finally:
        blocked_routes.discard("/blocked-endpoint")
