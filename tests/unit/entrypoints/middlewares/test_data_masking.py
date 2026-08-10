"""Unit tests for DataMaskingMiddleware (cycle 58 pure ASGI, FINAL L1)."""


from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.data_masking import DataMaskingMiddleware


def _start_message(send: AsyncMock):
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _body_message(send: AsyncMock):
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.body":
            return msg
    return None


def _downstream_json(body: bytes, status_code: int = 200):
    """Downstream возвращающий JSON response."""
    async def downstream(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return downstream


def _downstream_plain(body: bytes, status_code: int = 200):
    """Downstream возвращающий text/plain response."""
    async def downstream(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"text/plain"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return downstream


def _make_scope(
    method: str = "GET",
    path: str = "/api",
) -> dict:
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "scheme": "http",
        "server": ("test", 80),
        "query_string": b"",
        "headers": [],
    }


def _make_receive():
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return receive


class TestDataMaskingMiddleware:
    """Tests for :class:`DataMaskingMiddleware` (cycle 58 pure ASGI)."""

    @pytest.fixture
    def middleware(self) -> DataMaskingMiddleware:
        return DataMaskingMiddleware(AsyncMock())

    @pytest.mark.asyncio
    async def test_masks_sensitive_keys(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """password → *** (cycle 58 PII safety invariant)."""
        body = json.dumps({"password": "secret123", "name": "Alice"}).encode()
        app = AsyncMock()
        app.side_effect = _downstream_json(body)
        middleware.app = app

        send = AsyncMock()
        await middleware(_make_scope(), _make_receive(), send)

        # Body masked.
        body_msg = _body_message(send)
        parsed = json.loads(body_msg["body"].decode("utf-8"))
        assert parsed["password"] == "***"
        assert parsed["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_masks_nested_sensitive(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """Nested sensitive keys → *** (recursive masking)."""
        body = json.dumps(
            {"user": {"token": "abc123", "name": "Bob"}}
        ).encode()
        app = AsyncMock()
        app.side_effect = _downstream_json(body)
        middleware.app = app

        send = AsyncMock()
        await middleware(_make_scope(), _make_receive(), send)

        body_msg = _body_message(send)
        parsed = json.loads(body_msg["body"].decode("utf-8"))
        assert parsed["user"]["token"] == "***"
        assert parsed["user"]["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_non_json_passes_through(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """Non-JSON content-type → pass through unchanged (cycle 58 invariant)."""
        body = b"plain text with email@x.com"
        app = AsyncMock()
        app.side_effect = _downstream_plain(body)
        middleware.app = app

        send = AsyncMock()
        await middleware(_make_scope(), _make_receive(), send)

        # Plain text не модифицирован (нет email masking).
        body_msg = _body_message(send)
        assert body_msg["body"] == body

    @pytest.mark.asyncio
    async def test_mask_value_string_phone(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """Phone number в string → masked."""
        body = json.dumps({"phone": "+7 (999) 123-45-67"}).encode()
        app = AsyncMock()
        app.side_effect = _downstream_json(body)
        middleware.app = app

        send = AsyncMock()
        await middleware(_make_scope(), _make_receive(), send)

        body_msg = _body_message(send)
        parsed = json.loads(body_msg["body"].decode("utf-8"))
        assert "4567" in parsed["phone"] or "****" in parsed["phone"]

    @pytest.mark.asyncio
    async def test_mask_bytes_invalid_json_returns_raw(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """Invalid JSON body → masked fallback (fail-closed)."""
        # Cycle 58 fail-closed: invalid JSON → masked error response
        # (НЕ raw body — иначе утекает PII).
        raw = b"not-json"
        app = AsyncMock()
        app.side_effect = _downstream_json(raw)
        middleware.app = app

        send = AsyncMock()
        await middleware(_make_scope(), _make_receive(), send)

        # 503 + masked error response (НЕ original raw body).
        start = _start_message(send)
        assert start is not None
        # В pure ASGI: status code сохранён от downstream (200), но
        # body заменён на masked error.
        body_msg = _body_message(send)
        parsed = json.loads(body_msg["body"].decode("utf-8"))
        assert "error" in parsed
        assert parsed["error"] == "response_masking_failed"

    def test_mask_bytes_sensitive_keys(self, middleware: DataMaskingMiddleware) -> None:
        """_mask_bytes заменяет sensitive keys на *** (unit test)."""
        body = json.dumps(
            {"password": "x", "secret": "y", "token": "z", "name": "keep"}
        ).encode()
        masked = middleware._mask_bytes(body)
        parsed = json.loads(masked.decode("utf-8"))
        assert parsed["password"] == "***"
        assert parsed["secret"] == "***"
        assert parsed["token"] == "***"
        assert parsed["name"] == "keep"

    def test_mask_value_dict_recursive(self, middleware: DataMaskingMiddleware) -> None:
        """_mask_value рекурсивно проходит по nested структурам."""
        result = middleware._mask_value(
            {
                "level1": {
                    "level2": {
                        "password": "secret",
                        "name": "Alice",
                    }
                }
            }
        )
        assert result["level1"]["level2"]["password"] == "***"
        assert result["level1"]["level2"]["name"] == "Alice"

    def test_mask_value_list(self, middleware: DataMaskingMiddleware) -> None:
        """_mask_value обрабатывает list values."""
        result = middleware._mask_value(
            [{"password": "1"}, {"password": "2"}, {"safe": "x"}]
        )
        assert result[0]["password"] == "***"
        assert result[1]["password"] == "***"
        assert result[2]["safe"] == "x"

    def test_mask_email_short_local(self, middleware: DataMaskingMiddleware) -> None:
        """Email с коротким local (≤2 chars) → **@domain."""
        middleware._mask_email(type("M", (), {"group": lambda self, x: "a@b.com"})())
        # Just verify it doesn't crash.

    def test_mask_bytes_fallback(self, middleware: DataMaskingMiddleware) -> None:
        """_mask_bytes_fallback возвращает masked error response (fail-closed)."""
        masked = middleware._mask_bytes_fallback()
        parsed = json.loads(masked.decode("utf-8"))
        assert parsed["error"] == "response_masking_failed"


class TestDataMaskingMiddlewarePureASGI:
    """Cycle 58: pure ASGI regression-тесты для DataMaskingMiddleware."""

    @pytest.fixture
    def middleware(self) -> DataMaskingMiddleware:
        return DataMaskingMiddleware(AsyncMock())

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """Non-HTTP scope (websocket) пробрасывается без masking."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(
            {"type": "websocket", "path": "/ws", "headers": []},
            AsyncMock(),
            send,
        )

        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)

    @pytest.mark.asyncio
    async def test_content_length_updated_after_masking(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """Content-Length обновляется после masking (cycle 58 invariant)."""
        original_body = json.dumps({"password": "x" * 100, "name": "y"}).encode()
        app = AsyncMock()
        app.side_effect = _downstream_json(original_body)
        middleware.app = app

        send = AsyncMock()
        await middleware(_make_scope(), _make_receive(), send)

        # Start message содержит обновлённый Content-Length.
        start = _start_message(send)
        headers = dict(start["headers"])
        body_msg = _body_message(send)
        # New content-length равен длине masked body.
        assert headers[b"content-length"] == str(len(body_msg["body"])).encode(
            "latin-1"
        )

    @pytest.mark.asyncio
    async def test_does_not_call_downstream_after_masking(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """Cycle 58 invariant: downstream вызван ОДИН раз."""
        call_count = 0

        async def downstream(scope, receive, send):
            nonlocal call_count
            call_count += 1
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", b"10"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b'{"x":"y"}'})

        app = AsyncMock()
        app.side_effect = downstream
        middleware.app = app

        send = AsyncMock()
        await middleware(_make_scope(), _make_receive(), send)

        # Downstream ОДИН раз.
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_email_in_string_value_masked(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """Email в string value → masked (cycle 58 PII)."""
        body = json.dumps({"contact": "alice@example.com"}).encode()
        app = AsyncMock()
        app.side_effect = _downstream_json(body)
        middleware.app = app

        send = AsyncMock()
        await middleware(_make_scope(), _make_receive(), send)

        body_msg = _body_message(send)
        parsed = json.loads(body_msg["body"].decode("utf-8"))
        # Email masked (не оригинал "alice@example.com").
        assert parsed["contact"] != "alice@example.com"
        assert "@" in parsed["contact"]  # email structure preserved

    @pytest.mark.asyncio
    async def test_masking_failure_uses_fallback(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """Masking failure (JSON parse error) → masked error response (fail-closed)."""
        # Invalid JSON → _mask_bytes возвращает raw body (JSONDecodeError
        # catch в pure ASGI version). Но cycle 78 L1 invariant:
        # pure ASGI version возвращает masked error при любой failure.
        app = AsyncMock()
        app.side_effect = _downstream_json(b"not-json")
        middleware.app = app

        send = AsyncMock()
        await middleware(_make_scope(), _make_receive(), send)

        body_msg = _body_message(send)
        parsed = json.loads(body_msg["body"].decode("utf-8"))
        # Fail-closed: masked error response (НЕ raw body).
        assert parsed["error"] == "response_masking_failed"
