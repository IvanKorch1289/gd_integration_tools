"""Pure ASGI regression-тесты для RpaPolicyMiddleware (cycle 40).

Middleware deny-by-default для ``/api/v1/rpa/*`` endpoints. Cycle 40:
переписано с BaseHTTPMiddleware на pure ASGI — 403 response
отправляется напрямую через ``send()`` (НЕ raise, как в cycle 39).
"""


from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.entrypoints.middlewares.rpa_policy import RpaPolicyMiddleware


def _start_message(send: AsyncMock) -> dict | None:
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _body_message(send: AsyncMock) -> dict | None:
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.body":
            return msg
    return None


def _make_auth(roles: list[str] | set[str]) -> MagicMock:
    """Создаёт mock auth context с ролями."""
    auth = MagicMock()
    auth.roles = set(roles) if isinstance(roles, list) else roles
    return auth


@pytest.mark.asyncio
async def test_denies_403_when_no_auth_context() -> None:
    """RPA path без auth context → 403 (fail-closed)."""
    async def downstream(scope, receive, send):
        raise AssertionError("downstream должен быть skipped")

    app = AsyncMock()
    app.side_effect = downstream
    mw = RpaPolicyMiddleware(app=app)

    send = AsyncMock()
    await mw(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/rpa/shell/exec",
            "headers": [],
            "client": ("127.0.0.1", 0),
            "state": {},  # No auth context.
        },
        AsyncMock(),
        send,
    )

    start = _start_message(send)
    assert start is not None
    assert start["status"] == 403
    body = _body_message(send)
    parsed = json.loads(body["body"].decode("utf-8"))
    assert "detail" in parsed


@pytest.mark.asyncio
async def test_denies_403_when_role_not_in_auth_roles() -> None:
    """RPA path + auth без required role → 403."""
    async def downstream(scope, receive, send):
        raise AssertionError("downstream должен быть skipped")

    app = AsyncMock()
    app.side_effect = downstream
    mw = RpaPolicyMiddleware(app=app)

    send = AsyncMock()
    await mw(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/rpa/shell/exec",
            "headers": [],
            "client": ("10.0.0.1", 5000),
            "state": {"auth": _make_auth(["user", "guest"])},  # No rpa.admin
        },
        AsyncMock(),
        send,
    )

    start = _start_message(send)
    assert start is not None
    assert start["status"] == 403


@pytest.mark.asyncio
async def test_allows_when_role_in_auth_roles() -> None:
    """RPA path + auth с required role → pass through."""
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = AsyncMock()
    app.side_effect = downstream
    mw = RpaPolicyMiddleware(app=app)

    send = AsyncMock()
    await mw(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/rpa/script/run",
            "headers": [],
            "client": ("127.0.0.1", 0),
            "state": {"auth": _make_auth(["user", "rpa.admin"])},
        },
        AsyncMock(),
        send,
    )

    start = _start_message(send)
    assert start is not None
    assert start["status"] == 200


@pytest.mark.asyncio
async def test_passes_through_non_rpa_path_even_without_auth() -> None:
    """Non-RPA path не проверяет auth — pass through без auth context."""
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = AsyncMock()
    app.side_effect = downstream
    mw = RpaPolicyMiddleware(app=app)

    send = AsyncMock()
    await mw(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/users/list",
            "headers": [],
            "state": {},  # No auth — OK для non-RPA path.
        },
        AsyncMock(),
        send,
    )

    start = _start_message(send)
    assert start is not None
    assert start["status"] == 200


@pytest.mark.asyncio
async def test_custom_path_prefix() -> None:
    """Кастомный rpa_path_prefix — проверяется через custom prefix."""
    async def downstream(scope, receive, send):
        raise AssertionError("downstream должен быть skipped")

    app = AsyncMock()
    app.side_effect = downstream
    mw = RpaPolicyMiddleware(
        app=app, rpa_path_prefix="/api/v1/custom-rpa"
    )

    send = AsyncMock()
    await mw(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/custom-rpa/exec",
            "headers": [],
            "client": ("127.0.0.1", 0),
            "state": {},
        },
        AsyncMock(),
        send,
    )

    start = _start_message(send)
    assert start is not None
    assert start["status"] == 403


@pytest.mark.asyncio
async def test_passes_through_non_http_scope() -> None:
    """Non-HTTP scope (websocket) пробрасывается без role-gate."""
    async def downstream(scope, receive, send):
        await send({"type": "websocket.accept"})

    app = AsyncMock()
    app.side_effect = downstream
    mw = RpaPolicyMiddleware(app=app)

    send = AsyncMock()
    await mw(
        {"type": "websocket", "path": "/api/v1/rpa/ws", "headers": []},
        AsyncMock(),
        send,
    )

    # websocket.accept прошёл без 403.
    msg = send.await_args.args[0]
    assert msg["type"] == "websocket.accept"


@pytest.mark.asyncio
async def test_does_not_call_downstream_when_blocked() -> None:
    """Cycle 40 critical: при blocked path downstream НЕ вызывается.

    Если бы downstream был вызван, AssertionError пробросился бы.
    Тест прошёл = downstream не вызывался.
    """
    app = AsyncMock()

    async def downstream(scope, receive, send):
        raise AssertionError("downstream НЕ должен быть вызван")

    app.side_effect = downstream
    mw = RpaPolicyMiddleware(app=app)

    send = AsyncMock()
    await mw(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/rpa/shell/exec",
            "headers": [],
            "client": ("127.0.0.1", 0),
            "state": {},  # No auth → block
        },
        AsyncMock(),
        send,
    )

    # 403 отправлен.
    start = _start_message(send)
    assert start is not None
    assert start["status"] == 403


@pytest.mark.asyncio
async def test_handles_roles_as_list_or_set() -> None:
    """Middleware корректно обрабатывает roles как list И как set."""
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = AsyncMock()
    app.side_effect = downstream
    mw = RpaPolicyMiddleware(app=app)

    # roles как list (не set) — должен тоже работать.
    auth = MagicMock()
    auth.roles = ["rpa.admin", "viewer"]  # list, не set

    send = AsyncMock()
    await mw(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/rpa/exec",
            "headers": [],
            "client": ("127.0.0.1", 0),
            "state": {"auth": auth},
        },
        AsyncMock(),
        send,
    )

    start = _start_message(send)
    assert start is not None
    assert start["status"] == 200
