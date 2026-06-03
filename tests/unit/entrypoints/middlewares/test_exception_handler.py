"""Unit tests for ExceptionHandlerMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from starlette.responses import Response

from src.backend.core.errors import BaseError
from src.backend.entrypoints.middlewares.exception_handler import (
    ExceptionHandlerMiddleware,
)


class FakeBaseError(BaseError):
    """Fake BaseError for testing."""

    status_code = 418

    def to_dict(self) -> dict[str, object]:
        return {"message": "I am a teapot", "hasErrors": True}


class TestExceptionHandlerMiddleware:
    """Tests for :class:`ExceptionHandlerMiddleware`."""

    @pytest.fixture
    def middleware(self) -> ExceptionHandlerMiddleware:
        app = AsyncMock()
        return ExceptionHandlerMiddleware(app)

    @pytest.mark.asyncio
    async def test_no_exception_passes_through(
        self, middleware: ExceptionHandlerMiddleware
    ) -> None:
        """Normal response is returned unchanged."""
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

    @pytest.mark.asyncio
    async def test_base_error_handled(
        self, middleware: ExceptionHandlerMiddleware
    ) -> None:
        """BaseError subclasses produce structured response with custom status."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test")],
            }
        )
        call_next = AsyncMock(
            side_effect=FakeBaseError(message="boom", status_code=418)
        )

        result = await middleware.dispatch(request, call_next)

        assert result.status_code == 418
        body = result.body
        assert b"teapot" in body

    @pytest.mark.asyncio
    async def test_generic_error_500(
        self, middleware: ExceptionHandlerMiddleware
    ) -> None:
        """Generic exceptions produce HTTP 500."""
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

        result = await middleware.dispatch(request, call_next)

        assert result.status_code == 500
        body = result.body
        assert b"Internal server error" in body
        assert b"hasErrors" in body

    @pytest.mark.asyncio
    async def test_correlation_and_request_id_injected(
        self, middleware: ExceptionHandlerMiddleware
    ) -> None:
        """correlation_id and request_id are added to error payload."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/path",
                "path": "/path",
                "headers": [(b"host", b"test")],
            }
        )
        request.state.correlation_id = "corr-1"
        request.state.request_id = "req-1"
        call_next = AsyncMock(side_effect=ValueError("bad"))

        result = await middleware.dispatch(request, call_next)

        body = result.body
        assert b"corr-1" in body
        assert b"req-1" in body

    @pytest.mark.asyncio
    async def test_logs_on_generic_error(
        self, middleware: ExceptionHandlerMiddleware
    ) -> None:
        """Logger is invoked for generic exceptions."""
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

        with patch(
            "src.backend.entrypoints.middlewares.exception_handler.logger"
        ) as mock_logger:
            await middleware.dispatch(request, call_next)

        mock_logger.error.assert_called()
        mock_logger.exception.assert_called()
