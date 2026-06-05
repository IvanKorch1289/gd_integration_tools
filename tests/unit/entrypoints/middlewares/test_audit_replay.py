"""Unit tests for AuditReplayMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.backend.entrypoints.middlewares.audit_replay import (
    AuditReplayMiddleware,
    list_audit_records,
    replay_audit_record,
)


class TestAuditReplayMiddleware:
    """Tests for :class:`AuditReplayMiddleware`."""

    @pytest.fixture
    def middleware(self) -> AuditReplayMiddleware:
        return AuditReplayMiddleware(AsyncMock())

    @pytest.mark.asyncio
    async def test_skip_paths(self, middleware: AuditReplayMiddleware) -> None:
        """Health-like paths are skipped."""
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "url": "http://test/health",
                "path": "/health",
                "headers": [(b"host", b"test")],
            }
        )
        response = Response(content=b"ok")
        call_next = AsyncMock(return_value=response)

        result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sampling_excludes(self, middleware: AuditReplayMiddleware) -> None:
        """Sample rate can exclude requests."""
        middleware._sample_rate = 0.0
        request = Request(
            {
                "type": "http",
                "method": "GET",
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
    async def test_audit_record_sent(self, middleware: AuditReplayMiddleware) -> None:
        """Happy path: audit record is sent to Redis stream."""
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "url": "http://test/api",
                "path": "/api",
                "headers": [(b"host", b"test"), (b"x-correlation-id", b"corr-1")],
                "client": ("127.0.0.1", 1234),
            }
        )
        request._body = b'{"x":1}'
        response = Response(content=b"ok", status_code=201)
        call_next = AsyncMock(return_value=response)

        redis_mock = AsyncMock()
        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            result = await middleware.dispatch(request, call_next)

        assert result is response
        redis_mock.add_to_stream.assert_awaited_once()
        call_args = redis_mock.add_to_stream.await_args
        assert call_args is not None
        assert call_args.kwargs["stream_name"] == "audit:requests"

    @pytest.mark.asyncio
    async def test_uses_cached_body(self, middleware: AuditReplayMiddleware) -> None:
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
        request.state.body = b"cached-body"
        response = Response(content=b"ok", status_code=200)
        call_next = AsyncMock(return_value=response)

        redis_mock = AsyncMock()
        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            result = await middleware.dispatch(request, call_next)

        assert result is response
        call_args = redis_mock.add_to_stream.await_args
        assert call_args is not None
        assert call_args.kwargs["data"]["request_body"] == "cached-body"

    @pytest.mark.asyncio
    async def test_redis_unavailable(self, middleware: AuditReplayMiddleware) -> None:
        """Redis unavailability is handled gracefully."""
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

        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            result = await middleware.dispatch(request, call_next)

        assert result is response

    @pytest.mark.asyncio
    async def test_body_truncation(self, middleware: AuditReplayMiddleware) -> None:
        """Large bodies are truncated."""
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
        request.state.body = b"x" * 10000
        response = Response(content=b"ok", status_code=200)
        call_next = AsyncMock(return_value=response)

        redis_mock = AsyncMock()
        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            result = await middleware.dispatch(request, call_next)

        assert result is response
        call_args = redis_mock.add_to_stream.await_args
        assert call_args is not None
        assert len(call_args.kwargs["data"]["request_body"]) == 8192


class TestListAuditRecords:
    """Tests for :func:`list_audit_records`."""

    @pytest.mark.asyncio
    async def test_returns_records(self) -> None:
        """Happy path: returns list of records."""
        redis_mock = AsyncMock()
        redis_mock.read_stream.return_value = [{"id": "1", "path": "/api"}]

        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            records = await list_audit_records(count=10)

        assert records == [{"id": "1", "path": "/api"}]
        redis_mock.read_stream.assert_awaited_once_with(
            stream_name="audit:requests", count=10, start_id="-"
        )

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self) -> None:
        """Returns empty list on any exception."""
        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            side_effect=Exception("fail"),
        ):
            records = await list_audit_records()

        assert records == []


class TestReplayAuditRecord:
    """Tests for :func:`replay_audit_record`."""

    @pytest.mark.asyncio
    async def test_record_found(self) -> None:
        """Returns record data when found."""
        redis_mock = AsyncMock()
        redis_mock.read_stream.return_value = [
            {"method": "POST", "path": "/api", "request_body": "{}"}
        ]

        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            result = await replay_audit_record("123")

        assert result["status"] == "ready_for_replay"
        assert result["record_id"] == "123"
        assert result["method"] == "POST"

    @pytest.mark.asyncio
    async def test_record_not_found(self) -> None:
        """Returns error when record not found."""
        redis_mock = AsyncMock()
        redis_mock.read_stream.return_value = []

        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            result = await replay_audit_record("123")

        assert result["status"] == "error"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_error_on_read(self) -> None:
        """Returns error on Redis exception."""
        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            side_effect=Exception("fail"),
        ):
            result = await replay_audit_record("123")

        assert result["status"] == "error"
        assert "fail" in result["error"]
