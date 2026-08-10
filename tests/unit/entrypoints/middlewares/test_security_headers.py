"""Unit tests for SecurityHeadersMiddleware (pure ASGI).

Verifies that security headers (X-Content-Type-Options, X-Frame-Options,
Strict-Transport-Security, CSP, Permissions-Policy) are injected into every
HTTP response, override conflicting downstream headers, and that non-HTTP
scopes (e.g. WebSocket) pass through unmodified.

Cycle 78 L10: rewritten for pure ASGI middleware API. Previous version used
``mw.dispatch(request, call_next)`` (BaseHTTPMiddleware pattern) — but the
middleware is pure ASGI with ``__call__(scope, receive, send)``, so all
6 tests failed with AttributeError. Now uses ASGI triple directly.

S176 cycle 33 B-07 fix: middleware implementation is now actually pure
ASGI (was BaseHTTPMiddleware). The 7 base tests pass under both
implementations, but the new test_preserves_streaming_body_chunks
verifies the property that only the ASGI implementation can satisfy.
"""


from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.security_headers import (
    SecurityHeadersMiddleware,
)

# Expected header set injected by the middleware.
EXPECTED_HEADERS = {
    b"strict-transport-security": b"max-age=63072000; includeSubDomains",
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"content-security-policy": b"default-src 'self'",
    b"permissions-policy": b"geolocation=(), microphone=()",
}


def _http_scope() -> dict:
    """Minimal ASGI HTTP scope."""
    return {"type": "http", "method": "GET", "path": "/", "headers": []}


def _make_middleware() -> tuple[SecurityHeadersMiddleware, AsyncMock]:
    """Build middleware + mock downstream app that sends a 200 response."""
    inner = AsyncMock()

    async def downstream_app(scope, receive, send):
        # Start response (status + headers) + body.
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    inner.side_effect = downstream_app
    return SecurityHeadersMiddleware(inner), inner


def _captured_headers(send: AsyncMock) -> dict[bytes, bytes]:
    """Extract headers dict from ``http.response.start`` message."""
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return dict(msg.get("headers", []))
    return {}


@pytest.mark.asyncio
async def test_x_content_type_options_nosniff() -> None:
    """X-Content-Type-Options is set to nosniff to prevent MIME-sniffing."""
    mw, _ = _make_middleware()
    send = AsyncMock()
    await mw(_http_scope(), AsyncMock(), send)
    headers = _captured_headers(send)
    assert headers.get(b"x-content-type-options") == b"nosniff"


@pytest.mark.asyncio
async def test_x_frame_options_deny() -> None:
    """X-Frame-Options is set to DENY to prevent clickjacking."""
    mw, _ = _make_middleware()
    send = AsyncMock()
    await mw(_http_scope(), AsyncMock(), send)
    headers = _captured_headers(send)
    assert headers.get(b"x-frame-options") == b"DENY"


@pytest.mark.asyncio
async def test_strict_transport_security_header() -> None:
    """HSTS header is present with max-age and includeSubDomains."""
    mw, _ = _make_middleware()
    send = AsyncMock()
    await mw(_http_scope(), AsyncMock(), send)
    headers = _captured_headers(send)
    hsts = headers.get(b"strict-transport-security", b"").decode()
    assert "max-age=63072000" in hsts
    assert "includeSubDomains" in hsts


@pytest.mark.asyncio
async def test_all_security_headers_present() -> None:
    """The full expected security header set is injected."""
    mw, _ = _make_middleware()
    send = AsyncMock()
    await mw(_http_scope(), AsyncMock(), send)
    headers = _captured_headers(send)
    for header, expected_value in EXPECTED_HEADERS.items():
        assert headers.get(header) == expected_value, (
            f"header {header!r} mismatch"
        )


@pytest.mark.asyncio
async def test_headers_override_downstream_defaults() -> None:
    """Security headers override conflicting values set downstream."""
    mw, inner = _make_middleware()

    # Override inner app to send conflicting headers.
    async def conflicting_app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"x-frame-options", b"SAMEORIGIN"),
                    (b"x-content-type-options", b"text/html"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    inner.side_effect = conflicting_app
    send = AsyncMock()
    await mw(_http_scope(), AsyncMock(), send)
    headers = _captured_headers(send)
    assert headers[b"x-frame-options"] == b"DENY"
    assert headers[b"x-content-type-options"] == b"nosniff"


@pytest.mark.asyncio
async def test_non_http_scope_passthrough() -> None:
    """Non-HTTP (e.g. WebSocket) scopes pass through without header injection."""
    inner = AsyncMock()
    mw = SecurityHeadersMiddleware(inner)
    scope = {"type": "websocket", "path": "/ws", "headers": []}
    receive = AsyncMock()
    send = AsyncMock()
    await mw(scope, receive, send)
    # Inner app receives the scope unchanged.
    inner.assert_awaited_once_with(scope, receive, send)


@pytest.mark.asyncio
async def test_headers_added_to_error_response() -> None:
    """Security headers are present even on non-2xx responses."""
    mw, inner = _make_middleware()

    async def error_app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [],
            }
        )
        await send({"type": "http.response.body", "body": b"err"})

    inner.side_effect = error_app
    send = AsyncMock()
    await mw(_http_scope(), AsyncMock(), send)
    headers = _captured_headers(send)
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"x-frame-options"] == b"DENY"


# ── B-07 regression: pure ASGI must preserve streaming body chunks ──


@pytest.mark.asyncio
async def test_preserves_streaming_body_chunks() -> None:
    """B-07: pure ASGI не буферизует body — multiple http.response.body проходят как есть.

    Pre-fix (BaseHTTPMiddleware) буферизовал весь response.body в памяти
    до полного завершения ``await call_next(request)`` и только потом
    отправлял клиенту. Это ломает SSE/streaming и добавляет O(N) памяти
    на каждый запрос. Pure ASGI-вариант передаёт каждое ``http.response.body``
    сообщение downstream-send-у немедленно — body-chunks доходят в
    исходном порядке, без модификации.
    """
    inner = AsyncMock()
    chunks = [b"chunk-1\n", b"chunk-2\n", b"chunk-3\n"]

    async def streaming_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        for chunk in chunks:
            await send({"type": "http.response.body", "body": chunk})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    inner.side_effect = streaming_app
    mw = SecurityHeadersMiddleware(inner)
    send = AsyncMock()
    await mw(_http_scope(), AsyncMock(), send)

    # Find all body messages in order.
    body_messages = [
        call.args[0] for call in send.await_args_list
        if call.args[0]["type"] == "http.response.body"
    ]
    assert len(body_messages) == 4  # 3 chunks + 1 final empty
    assert body_messages[0]["body"] == b"chunk-1\n"
    assert body_messages[1]["body"] == b"chunk-2\n"
    assert body_messages[2]["body"] == b"chunk-3\n"
    # Final message has more_body=False (stream terminator).
    assert body_messages[3].get("more_body") is False


@pytest.mark.asyncio
async def test_does_not_buffer_headers_until_body_complete() -> None:
    """B-07: http.response.start отправляется до любого body-сообщения.

    BaseHTTPMiddleware переупорядочивал сообщения: downstream мог
    отправить headers + body, но BaseHTTPMiddleware ждал body-complete
    перед тем как начать отправлять. Это нарушает backpressure. В pure
    ASGI порядок строго сохраняется.
    """
    inner = AsyncMock()
    seen_types: list[str] = []

    async def mixed_app(scope, receive, send):
        seen_types.append("app:start")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        seen_types.append("app:body1")
        await send({"type": "http.response.body", "body": b"hello"})
        seen_types.append("app:body2")
        await send({"type": "http.response.body", "body": b"world"})

    inner.side_effect = mixed_app
    mw = SecurityHeadersMiddleware(inner)
    send = AsyncMock()
    await mw(_http_scope(), AsyncMock(), send)

    # The downstream app must see start → body1 → body2 in that order.
    assert seen_types == ["app:start", "app:body1", "app:body2"]
    # And the headers we inject must appear on the FIRST http.response.start.
    start_idx = next(
        i for i, c in enumerate(send.await_args_list)
        if c.args[0]["type"] == "http.response.start"
    )
    body1_idx = next(
        i
        for i, c in enumerate(send.await_args_list[start_idx + 1 :], start=start_idx + 1)
        if c.args[0]["type"] == "http.response.body"
    )
    assert start_idx < body1_idx, "headers must be sent before any body chunk"
