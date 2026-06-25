"""Unit tests for ResponseCacheMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Request, Response

from src.backend.entrypoints.middlewares.response_cache import ResponseCacheMiddleware


def _json_response(body: bytes, status_code: int = 200) -> Response:
    """Build JSON Response with pre-seeded body_iterator."""
    resp = Response(
        content=body, media_type="application/json", status_code=status_code
    )

    async def _iter():
        yield body

    resp.body_iterator = _iter()  # type: ignore[attr-defined]
    return resp


class TestResponseCacheMiddleware:
    """Tests for :class:`ResponseCacheMiddleware`."""

    @pytest.fixture
    def middleware(self) -> ResponseCacheMiddleware:
        return ResponseCacheMiddleware(AsyncMock(), max_age=120)

    @pytest.mark.asyncio
    async def test_non_get_passes_through(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Non-GET requests skip caching."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test")],
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_200_passes_through(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Non-200 GET responses skip caching."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test")],
            }
        )
        response = _json_response(b'{"err":1}', status_code=500)
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response

    @pytest.mark.asyncio
    async def test_non_json_passes_through(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Non-JSON GET 200 responses skip caching."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test")],
            }
        )
        response = Response(content=b"plain", media_type="text/plain")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response

    @pytest.mark.asyncio
    async def test_adds_etag_and_cache_control(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """JSON 200 GET adds ETag and Cache-Control headers."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test")],
            }
        )
        body = b'{"data":1}'
        response = _json_response(body)
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result.headers.get("ETag")
        assert result.headers.get("Cache-Control") == "public, max-age=120"
        # body_iterator restored
        chunks = [chunk async for chunk in result.body_iterator]
        assert b"".join(chunks) == body

    @pytest.mark.asyncio
    async def test_if_none_match_returns_304(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Matching If-None-Match returns 304."""
        body = b'{"data":1}'

        with (
            patch.object(middleware, "_capture_body", return_value=body),
            patch(
                "src.backend.entrypoints.middlewares.response_cache._USE_XXHASH", False
            ),
            patch(
                "src.backend.entrypoints.middlewares._body_hash.etag_hash",
                return_value='"abc1230000000000"',
            ),
        ):
            expected_etag = '"abc1230000000000"'

            request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "url": "http://test/api",
                    "path": "/api",
                    "headers": [
                        (b"host", b"test"),
                        (b"if-none-match", expected_etag.encode()),
                    ],
                }
            )
            response = _json_response(body)
            call_next = AsyncMock(return_value=response)

            result = await middleware.dispatch(request, call_next)

        assert result.status_code == 304
        assert result.headers["ETag"] == expected_etag

    @pytest.mark.asyncio
    async def test_if_none_match_mismatch_returns_200(
        self, middleware: ResponseCacheMiddleware
    ) -> None:
        """Mismatched If-None-Match returns 200 with new ETag."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test"), (b"if-none-match", b'"old"')],
            }
        )
        body = b'{"data":1}'
        response = _json_response(body)
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result.status_code == 200
        assert result.headers["ETag"] != '"old"'
        assert result.headers["Cache-Control"] == "public, max-age=120"

    @pytest.mark.asyncio
    async def test_capture_body(self, middleware: ResponseCacheMiddleware) -> None:
        """_capture_body aggregates chunks."""
        resp = Response(content=b"hello world")

        async def _iter():
            yield b"hello "
            yield b"world"

        resp.body_iterator = _iter()  # type: ignore[attr-defined]

        body = await middleware._capture_body(resp)
        assert body == b"hello world"
