"""Pure ASGI regression-тесты для AuthMethodHeaderMiddleware (cycle 37).

Middleware добавляет ``X-Auth-Method`` header в response на основе
``scope['state']['auth'].method``. S191 security: default = disabled
(information disclosure prevention).

Cycle 37: middleware переписан с BaseHTTPMiddleware на pure ASGI.
Auth context устанавливается downstream (auth_selector пишет в
``scope['state']`` ПОСЛЕ нашего __call__), поэтому header value
вычисляется ВНУТРИ send-wrapper, а не в __call__.
"""


from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.auth_method_header import (
    AuthMethodHeaderMiddleware,
)


def _make_scope(
    method: str = "GET",
    path: str = "/",
    state: dict | None = None,
) -> dict:
    """ASGI HTTP scope для тестов."""
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        **({"state": state} if state is not None else {}),
    }


def _captured_start_headers(send: AsyncMock) -> dict[bytes, bytes]:
    """Извлекает headers из ``http.response.start`` сообщения."""
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return dict(msg.get("headers", []))
    return {}


@pytest.mark.asyncio
async def test_emits_header_when_enabled_and_auth_context_set() -> None:
    """enabled=True + downstream установил state['auth'] → header emit."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        # Auth middleware имитирует установку state['auth'].
        scope.setdefault("state", {})["auth"] = type(
            "AuthCtx", (), {"method": type("M", (), {"value": "jwt"})()},
        )()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = AuthMethodHeaderMiddleware(app, enabled=True)
    send = AsyncMock()
    await mw(_make_scope(), AsyncMock(), send)

    headers = _captured_start_headers(send)
    assert headers[b"x-auth-method"] == b"jwt"


@pytest.mark.asyncio
async def test_no_header_when_disabled_default() -> None:
    """S191: enabled=False (default) → НЕ emit'ит header (security default)."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        scope.setdefault("state", {})["auth"] = type(
            "AuthCtx", (), {"method": type("M", (), {"value": "jwt"})()},
        )()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = AuthMethodHeaderMiddleware(app)  # enabled=False default
    send = AsyncMock()
    await mw(_make_scope(), AsyncMock(), send)

    headers = _captured_start_headers(send)
    assert b"x-auth-method" not in headers


@pytest.mark.asyncio
async def test_no_header_when_auth_context_missing() -> None:
    """enabled=True, но downstream не установил state['auth'] → no header."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        # No state['auth'] set.
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = AuthMethodHeaderMiddleware(app, enabled=True)
    send = AsyncMock()
    await mw(_make_scope(), AsyncMock(), send)

    headers = _captured_start_headers(send)
    assert b"x-auth-method" not in headers


@pytest.mark.asyncio
async def test_header_value_uses_method_value_attr() -> None:
    """Если method имеет .value attr (Enum-like) → используется оно."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        scope.setdefault("state", {})["auth"] = type(
            "AuthCtx", (), {"method": type("M", (), {"value": "api_key"})()},
        )()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = AuthMethodHeaderMiddleware(app, enabled=True)
    send = AsyncMock()
    await mw(_make_scope(), AsyncMock(), send)

    headers = _captured_start_headers(send)
    assert headers[b"x-auth-method"] == b"api_key"


@pytest.mark.asyncio
async def test_custom_header_name() -> None:
    """header_name параметр — кастомное имя response header."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        scope.setdefault("state", {})["auth"] = type(
            "AuthCtx", (), {"method": type("M", (), {"value": "jwt"})()},
        )()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = AuthMethodHeaderMiddleware(app, header_name="X-Custom-Auth", enabled=True)
    send = AsyncMock()
    await mw(_make_scope(), AsyncMock(), send)

    headers = _captured_start_headers(send)
    assert headers[b"x-custom-auth"] == b"jwt"


@pytest.mark.asyncio
async def test_passes_through_non_http_scope() -> None:
    """Non-HTTP scope (websocket) пробрасывается без изменений."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "websocket.accept"})

    app.side_effect = downstream
    mw = AuthMethodHeaderMiddleware(app, enabled=True)
    send = AsyncMock()
    await mw({"type": "websocket", "path": "/ws", "headers": []}, AsyncMock(), send)

    # websocket.accept прошёл без header injection.
    msg = send.await_args.args[0]
    assert msg["type"] == "websocket.accept"
    assert "headers" not in msg or b"x-auth-method" not in dict(msg.get("headers", []))


@pytest.mark.asyncio
async def test_preserves_body_chunks_unchanged() -> None:
    """Body-сообщения пробрасываются без модификации (cycle 37 invariant)."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        scope.setdefault("state", {})["auth"] = type(
            "AuthCtx", (), {"method": type("M", (), {"value": "jwt"})()},
        )()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"chunk-1"})
        await send({"type": "http.response.body", "body": b"chunk-2"})

    app.side_effect = downstream
    mw = AuthMethodHeaderMiddleware(app, enabled=True)
    send = AsyncMock()
    await mw(_make_scope(), AsyncMock(), send)

    body_msgs = [
        c.args[0] for c in send.await_args_list
        if c.args[0]["type"] == "http.response.body"
    ]
    assert len(body_msgs) == 2
    assert body_msgs[0]["body"] == b"chunk-1"
    assert body_msgs[1]["body"] == b"chunk-2"
