"""Unit tests for InnerRequestLoggingMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.backend.entrypoints.middlewares.request_log import (
    InnerRequestLoggingMiddleware,
)


class TestInnerRequestLoggingMiddleware:
    """Tests for :class:`InnerRequestLoggingMiddleware`."""

    @pytest.fixture
    def middleware(self) -> InnerRequestLoggingMiddleware:
        app = AsyncMock()
        mw = InnerRequestLoggingMiddleware(app)
        mw.logger = MagicMock()
        mw.log_body = False
        mw.max_body_size = 1000
        return mw

    @pytest.mark.asyncio
    async def test_logs_request_and_response(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """Logs request method/URL and response status."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test")],
            }
        )
        response = Response(content=b"ok", status_code=200)
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response
        middleware.logger.info.assert_any_call("Запрос: GET http://test/path")
        assert any(
            "Ответ: 200" in str(call) for call in middleware.logger.info.call_args_list
        )

    @pytest.mark.asyncio
    async def test_logs_post_body_when_enabled(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """Logs POST body when log_body is enabled."""
        middleware.log_body = True
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"content-type", b"application/json")],
            }
        )
        request._body = b'{"data": 1}'
        response = Response(content=b"ok", status_code=201)

        async def _iter():
            yield b"ok"

        response.body_iterator = _iter()  # type: ignore[attr-defined]
        call_next = AsyncMock(return_value=response)

        with patch.object(
            middleware, "_get_request_body", return_value=b'{"data": 1}'
        ) as mock_get_body:
            await middleware.dispatch(request, call_next)

        mock_get_body.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_logs_error_on_exception(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """Logs error when call_next raises."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test")],
            }
        )
        call_next = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError, match="boom"):
            await middleware.dispatch(request, call_next)

        middleware.logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_request_body_from_cache(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """_get_request_body uses cached body from request.state."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test")],
            }
        )
        request.state.body = b"cached"

        body = await middleware._get_request_body(request)

        assert body == b"cached"

    @pytest.mark.asyncio
    async def test_get_request_body_too_large(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """_get_request_body returns placeholder when body exceeds max size."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test")],
            }
        )
        request.state.body = b"x" * 2000
        middleware.max_body_size = 100

        body = await middleware._get_request_body(request)

        assert "слишком велико".encode() in body

    @pytest.mark.asyncio
    async def test_capture_response_body(
        self, middleware: InnerRequestLoggingMiddleware
    ) -> None:
        """_capture_response_body collects chunks and restores iterator."""
        from starlette.responses import StreamingResponse

        async def _iter():
            yield b"hello world"

        response = StreamingResponse(content=_iter(), status_code=200)

        body = await middleware._capture_response_body(response)

        assert body == b"hello world"
        chunks = [chunk async for chunk in response.body_iterator]
        assert b"".join(chunks) == b"hello world"
