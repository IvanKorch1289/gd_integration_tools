"""Unit tests for BrotliCompressionMiddleware."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.entrypoints.middlewares.brotli_compression import (
    BrotliCompressionMiddleware,
)


class _SendCollector:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def __call__(self, message: dict[str, Any]) -> None:
        self.messages.append(message)


@pytest.fixture
def inner_app() -> AsyncMock:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"key": "value"}' * 50})

    return app


class TestBrotliCompressionMiddleware:
    """Tests for :class:`BrotliCompressionMiddleware`."""

    @pytest.mark.asyncio
    async def test_no_brotli_module_noop(self, inner_app: Any) -> None:
        """Without brotli module, middleware passes through."""
        mw = BrotliCompressionMiddleware(inner_app)
        mw._brotli = None

        send = _SendCollector()
        await mw({"type": "http"}, AsyncMock(), send)

        assert len(send.messages) == 2
        assert send.messages[1]["body"] == b'{"key": "value"}' * 50

    @pytest.mark.asyncio
    async def test_compresses_json_when_accepted(self, inner_app: Any) -> None:
        """Compresses JSON response when client accepts brotli."""
        brotli = MagicMock()
        brotli.compress.return_value = b"compressed"

        mw = BrotliCompressionMiddleware(inner_app, minimum_size=10)
        mw._brotli = brotli

        send = _SendCollector()
        await mw(
            {"type": "http", "headers": [(b"accept-encoding", b"br")]},
            AsyncMock(),
            send,
        )

        assert len(send.messages) == 2
        headers = send.messages[0]["headers"]
        assert (b"content-type", b"application/json") in headers
        assert (b"content-encoding", b"br") in headers
        assert any(
            h[0] == b"vary" and b"accept-encoding" in h[1].lower() for h in headers
        )
        assert send.messages[1]["body"] == b"compressed"
        brotli.compress.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_compress_when_not_accepted(self, inner_app: Any) -> None:
        """Does not compress when client does not accept brotli."""
        brotli = MagicMock()

        async def app(scope: Any, receive: Any, send: Any) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"key": "value"}' * 50})

        mw = BrotliCompressionMiddleware(app, minimum_size=10)
        mw._brotli = brotli

        send = _SendCollector()
        await mw({"type": "http"}, AsyncMock(), send)

        brotli.compress.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_compress_for_small_response(self, inner_app: Any) -> None:
        """Does not compress responses below minimum size."""
        brotli = MagicMock()

        async def app(scope: Any, receive: Any, send: Any) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"k": 1}'})

        mw = BrotliCompressionMiddleware(app, minimum_size=100)
        mw._brotli = brotli

        send = _SendCollector()
        await mw({"type": "http"}, AsyncMock(), send)

        brotli.compress.assert_not_called()

    def test_wants_brotli_true(self) -> None:
        """_wants_brotli returns True when br is present."""
        headers = [(b"accept-encoding", b"gzip, br, deflate")]
        assert BrotliCompressionMiddleware._wants_brotli(headers) is True

    def test_wants_brotli_false(self) -> None:
        """_wants_brotli returns False when br is absent."""
        headers = [(b"accept-encoding", b"gzip, deflate")]
        assert BrotliCompressionMiddleware._wants_brotli(headers) is False

    def test_is_json_true(self) -> None:
        """_is_json returns True for application/json."""
        headers = [(b"content-type", b"application/json; charset=utf-8")]
        assert BrotliCompressionMiddleware._is_json(headers) is True

    def test_is_json_false(self) -> None:
        """_is_json returns False for text/html."""
        headers = [(b"content-type", b"text/html")]
        assert BrotliCompressionMiddleware._is_json(headers) is False

    def test_try_import_brotli_none_when_missing(self) -> None:
        """_try_import_brotli returns None when brotli is not installed."""
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            result = BrotliCompressionMiddleware._try_import_brotli()
        assert result is None
