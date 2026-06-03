"""Unit tests for RequestBodyCacheMiddleware."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request, Response

from src.backend.entrypoints.middlewares.request_body_cache import (
    RequestBodyCacheMiddleware,
    cached_body,
)


class TestRequestBodyCacheMiddleware:
    """Tests for :class:`RequestBodyCacheMiddleware`."""

    @pytest.fixture
    def middleware(self) -> RequestBodyCacheMiddleware:
        return RequestBodyCacheMiddleware(AsyncMock(), max_body_size=1024)

    @pytest.mark.asyncio
    async def test_bodyless_methods_skip(
        self, middleware: RequestBodyCacheMiddleware
    ) -> None:
        """GET/HEAD/OPTIONS/DELETE/TRACE skip caching."""
        for method in ("GET", "HEAD", "OPTIONS", "DELETE", "TRACE"):
            request = Request(
                {
                    "type": "http",
                    "method": method,
                    "url": "http://test/path",
                    "path": "/path",
                    "headers": [(b"host", b"test")],
                }
            )
            response = Response(content=b"ok")
            call_next = AsyncMock(return_value=response)

            result = await middleware.dispatch(request, call_next)
            assert result is response
            assert not hasattr(request.state, "body")

    @pytest.mark.asyncio
    async def test_content_length_too_large(
        self, middleware: RequestBodyCacheMiddleware
    ) -> None:
        """Large Content-Length skips caching."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test"), (b"content-length", b"2048")],
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)
        assert result is response
        assert not hasattr(request.state, "body")

    @pytest.mark.asyncio
    async def test_normal_body_cached_and_replay_installed(
        self, middleware: RequestBodyCacheMiddleware
    ) -> None:
        """Normal body is cached and _receive is overridden."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test")],
            }
        )
        request._body = b"hello"
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response
        assert request.state.body == b"hello"
        msg1 = await request._receive()
        assert msg1["type"] == "http.request"
        assert msg1["body"] == b"hello"
        assert msg1["more_body"] is False
        msg2 = await request._receive()
        assert msg2["type"] == "http.disconnect"

    @pytest.mark.asyncio
    async def test_body_exceeds_max_after_read(
        self, middleware: RequestBodyCacheMiddleware
    ) -> None:
        """Body read but too large: replay installed but not cached."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test")],
            }
        )
        request._body = b"x" * 2048
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response
        assert not hasattr(request.state, "body")
        msg = await request._receive()
        assert msg["body"] == b"x" * 2048

    @pytest.mark.asyncio
    async def test_body_read_failure(
        self, middleware: RequestBodyCacheMiddleware
    ) -> None:
        """Failure to read body passes through gracefully."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test")],
            }
        )

        async def _bad_receive() -> dict[str, Any]:
            raise RuntimeError("recv error")

        request._receive = _bad_receive

        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)
        assert result is response

    def test_parse_content_length_valid(
        self, middleware: RequestBodyCacheMiddleware
    ) -> None:
        """_parse_content_length returns int for valid header."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"content-length", b"42")],
            }
        )
        assert middleware._parse_content_length(request) == 42

    def test_parse_content_length_missing(
        self, middleware: RequestBodyCacheMiddleware
    ) -> None:
        """_parse_content_length returns None when header absent."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [],
            }
        )
        assert middleware._parse_content_length(request) is None

    def test_parse_content_length_invalid(
        self, middleware: RequestBodyCacheMiddleware
    ) -> None:
        """_parse_content_length returns None for invalid value."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"content-length", b"abc")],
            }
        )
        assert middleware._parse_content_length(request) is None

    @pytest.mark.asyncio
    async def test_install_replay_receive(
        self, middleware: RequestBodyCacheMiddleware
    ) -> None:
        """_install_replay_receive provides correct ASGI messages."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [],
            }
        )
        middleware._install_replay_receive(request, b"payload")

        msg1 = await request._receive()
        assert msg1 == {"type": "http.request", "body": b"payload", "more_body": False}
        msg2 = await request._receive()
        assert msg2 == {"type": "http.disconnect"}


class TestCachedBodyHelper:
    """Tests for :func:`cached_body`."""

    def test_returns_cached_bytes(self) -> None:
        """Returns cached body when present."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [],
            }
        )
        request.state.body = b"cached"
        assert cached_body(request) == b"cached"

    def test_returns_none_when_missing(self) -> None:
        """Returns None when body is not cached."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [],
            }
        )
        assert cached_body(request) is None

    def test_returns_none_for_wrong_type(self) -> None:
        """Returns None when body is not bytes-like."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [],
            }
        )
        request.state.body = "string"
        assert cached_body(request) is None
