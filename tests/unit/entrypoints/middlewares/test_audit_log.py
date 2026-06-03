"""Unit tests for AuditLogMiddleware."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.backend.entrypoints.middlewares.audit_log import AuditLogMiddleware


class TestAuditLogMiddleware:
    """Tests for :class:`AuditLogMiddleware`."""

    @pytest.fixture
    def middleware(self) -> AuditLogMiddleware:
        app = AsyncMock()
        mw = AuditLogMiddleware(app)
        mw.logger = MagicMock()
        return mw

    @pytest.mark.asyncio
    async def test_logs_and_returns_response(
        self, middleware: AuditLogMiddleware
    ) -> None:
        """Happy path: logs audit event and returns response."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test"), (b"user-agent", b"pytest")],
                "client": ("127.0.0.1", 1234),
            }
        )
        request.state.client_id = "client-42"
        request.state.request_id = "req-1"
        request.state.correlation_id = "corr-1"
        request._body = b'{"x":1}'

        response = Response(content=b"ok", status_code=200)
        call_next = AsyncMock(return_value=response)

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ) as mock_redis_provider,
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ) as mock_ch_provider,
        ):
            result = await middleware.dispatch(request, call_next)

        assert result is response
        middleware.logger.info.assert_called()
        mock_redis_provider.return_value.add_to_stream.assert_awaited_once()
        mock_ch_provider.return_value.insert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uses_cached_body(self, middleware: AuditLogMiddleware) -> None:
        """Uses request.state.body when available."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test")],
                "client": ("127.0.0.1", 1234),
            }
        )
        request.state.body = b"cached"

        response = Response(content=b"ok", status_code=200)
        call_next = AsyncMock(return_value=response)

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ),
        ):
            result = await middleware.dispatch(request, call_next)

        assert result is response

    @pytest.mark.asyncio
    async def test_body_read_failure_graceful(
        self, middleware: AuditLogMiddleware
    ) -> None:
        """Graceful fallback when body reading fails."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test")],
                "client": ("127.0.0.1", 1234),
            }
        )

        # Force request.body() to fail
        async def _bad_receive() -> dict[str, Any]:
            raise RuntimeError("recv error")

        request._receive = _bad_receive

        response = Response(content=b"ok", status_code=200)
        call_next = AsyncMock(return_value=response)

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ),
        ):
            result = await middleware.dispatch(request, call_next)

        assert result is response

    @pytest.mark.asyncio
    async def test_redis_failure_ignored(self, middleware: AuditLogMiddleware) -> None:
        """Redis stream error is silently ignored."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test")],
                "client": ("127.0.0.1", 1234),
            }
        )
        response = Response(content=b"ok", status_code=200)
        call_next = AsyncMock(return_value=response)

        redis_mock = AsyncMock()
        redis_mock.add_to_stream.side_effect = ConnectionError("redis down")

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=redis_mock,
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ),
        ):
            result = await middleware.dispatch(request, call_next)

        assert result is response

    @pytest.mark.asyncio
    async def test_clickhouse_failure_ignored(
        self, middleware: AuditLogMiddleware
    ) -> None:
        """ClickHouse insert error is silently ignored."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test")],
                "client": ("127.0.0.1", 1234),
            }
        )
        response = Response(content=b"ok", status_code=200)
        call_next = AsyncMock(return_value=response)

        ch_mock = AsyncMock()
        ch_mock.insert.side_effect = Exception("ch down")

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=ch_mock,
            ),
        ):
            result = await middleware.dispatch(request, call_next)

        assert result is response

    @pytest.mark.asyncio
    async def test_no_client_defaults(self, middleware: AuditLogMiddleware) -> None:
        """Missing client defaults to 'unknown' IP."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test")],
            }
        )
        response = Response(content=b"ok", status_code=200)
        call_next = AsyncMock(return_value=response)

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ),
        ):
            result = await middleware.dispatch(request, call_next)

        assert result is response
        log_call = middleware.logger.info.call_args_list[0]
        assert "ip=unknown" in log_call[0][0] or any(
            "unknown" in str(a) for a in log_call[0]
        )
