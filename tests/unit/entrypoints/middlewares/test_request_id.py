"""Pure ASGI regression-тесты для RequestIDMiddleware (cycle 36).

RequestIDMiddleware — критический tracing-middleware: добавляет
X-Request-ID и X-Correlation-ID в каждый request/response. От
корректности этих заголовков зависит observability всех downstream
компонентов (логи, audit-events, gRPC metadata, message queues).

Cycle 36: middleware переписан с BaseHTTPMiddleware на pure ASGI.
Без тестов — регрессии в API (например, headers не применяются
для streaming responses, race condition в send-order) не были бы
пойманы.
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.request_id import RequestIDMiddleware


def _make_scope(
    method: str = "GET",
    path: str = "/",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict:
    """ASGI HTTP scope для тестов."""
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
    }


def _captured_start_headers(send: AsyncMock) -> dict[bytes, bytes]:
    """Извлекает headers из ``http.response.start`` сообщения."""
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return dict(msg.get("headers", []))
    return {}


@pytest.mark.asyncio
async def test_generates_request_id_and_correlation_id_when_absent() -> None:
    """Без incoming headers — генерируются UUID4 hex (32 chars)."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = RequestIDMiddleware(app)
    send = AsyncMock()
    await mw(_make_scope(), AsyncMock(), send)

    headers = _captured_start_headers(send)
    assert len(headers[b"x-request-id"]) == 32
    assert len(headers[b"x-correlation-id"]) == 32
    # Оба ID разные (UUID4).
    assert headers[b"x-request-id"] != headers[b"x-correlation-id"]


@pytest.mark.asyncio
async def test_preserves_incoming_request_id() -> None:
    """Incoming X-Request-ID пробрасывается в response header."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = RequestIDMiddleware(app)
    send = AsyncMock()
    await mw(
        _make_scope(headers=[(b"x-request-id", b"client-req-123")]),
        AsyncMock(),
        send,
    )

    headers = _captured_start_headers(send)
    assert headers[b"x-request-id"] == b"client-req-123"
    # correlation_id сгенерирован (не передан клиентом).
    assert len(headers[b"x-correlation-id"]) == 32


@pytest.mark.asyncio
async def test_preserves_incoming_correlation_id() -> None:
    """Incoming X-Correlation-ID пробрасывается в response header."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = RequestIDMiddleware(app)
    send = AsyncMock()
    await mw(
        _make_scope(headers=[(b"x-correlation-id", b"trace-abc-789")]),
        AsyncMock(),
        send,
    )

    headers = _captured_start_headers(send)
    assert headers[b"x-correlation-id"] == b"trace-abc-789"


@pytest.mark.asyncio
async def test_sets_request_state_for_downstream() -> None:
    """scope['state'] устанавливается с request_id + correlation_id."""
    captured_scope: dict = {}

    async def downstream(scope, receive, send):
        captured_scope.update(scope)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = AsyncMock()
    app.side_effect = downstream
    mw = RequestIDMiddleware(app)
    send = AsyncMock()
    await mw(_make_scope(), AsyncMock(), send)

    state = captured_scope.get("state", {})
    assert "request_id" in state
    assert "correlation_id" in state
    assert len(state["request_id"]) == 32
    assert len(state["correlation_id"]) == 32


@pytest.mark.asyncio
async def test_overrides_existing_response_headers() -> None:
    """Если downstream уже послал X-Request-ID — перезаписываем (force our value)."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        # Downstream пытается послать свой X-Request-ID — мы его перезапишем.
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"x-request-id", b"downstream-stale-id"),
                    (b"content-type", b"application/json"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    app.side_effect = downstream
    mw = RequestIDMiddleware(app)
    send = AsyncMock()
    await mw(_make_scope(), AsyncMock(), send)

    headers = _captured_start_headers(send)
    # Наш ID (32 chars UUID4) — НЕ downstream value.
    assert len(headers[b"x-request-id"]) == 32
    assert headers[b"x-request-id"] != b"downstream-stale-id"
    # Другие headers downstream сохранены.
    assert headers[b"content-type"] == b"application/json"


@pytest.mark.asyncio
async def test_preserves_body_chunks_unchanged() -> None:
    """Body-сообщения пробрасываются как есть (middleware не трогает body)."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"chunk-1"})
        await send({"type": "http.response.body", "body": b"chunk-2"})
        await send(
            {"type": "http.response.body", "body": b"", "more_body": False}
        )

    app.side_effect = downstream
    mw = RequestIDMiddleware(app)
    send = AsyncMock()
    await mw(_make_scope(), AsyncMock(), send)

    # Извлекаем body messages в порядке.
    body_msgs = [
        c.args[0] for c in send.await_args_list
        if c.args[0]["type"] == "http.response.body"
    ]
    assert len(body_msgs) == 3
    assert body_msgs[0]["body"] == b"chunk-1"
    assert body_msgs[1]["body"] == b"chunk-2"
    assert body_msgs[2].get("more_body") is False


@pytest.mark.asyncio
async def test_passes_through_non_http_scope() -> None:
    """Non-HTTP scope (websocket/lifespan) пробрасывается без изменений."""
    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "websocket.accept"})

    app.side_effect = downstream
    mw = RequestIDMiddleware(app)
    send = AsyncMock()
    await mw(
        {"type": "websocket", "path": "/ws", "headers": []},
        AsyncMock(),
        send,
    )
    # Downstream получил scope БЕЗ модификации state.
    app.assert_awaited_once()
    scope_arg = app.await_args.args[0]
    assert scope_arg["type"] == "websocket"
    # websocket accept message прошёл без tracing headers
    # (middleware не инжектит их для non-HTTP scope).
    sent_msg = send.await_args.args[0]
    assert sent_msg["type"] == "websocket.accept"
