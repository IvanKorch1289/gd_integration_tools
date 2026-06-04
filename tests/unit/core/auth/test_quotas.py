"""Unit tests for src.backend.core.auth.quotas."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.auth.quotas import (
    QuotaCheckMiddleware,
    QuotaPolicy,
    default_tenant_extractor,
)


class TestDefaultTenantExtractor:
    def test_non_http(self) -> None:
        assert default_tenant_extractor({"type": "websocket"}) is None

    def test_no_header(self) -> None:
        assert default_tenant_extractor({"type": "http", "headers": []}) is None

    def test_has_header(self) -> None:
        scope = {"type": "http", "headers": [(b"x-tenant-id", b"tenant-1")]}
        assert default_tenant_extractor(scope) == "tenant-1"


class TestQuotaPolicy:
    def test_should_skip(self) -> None:
        service = MagicMock()
        policy = QuotaPolicy(service=service)
        assert policy.should_skip({"path": "/health"}) is True
        assert policy.should_skip({"path": "/api/v1/users"}) is False

    @pytest.mark.asyncio
    async def test_check(self) -> None:
        service = AsyncMock()
        service.consume_request = AsyncMock(return_value=MagicMock(allowed=True))
        policy = QuotaPolicy(service=service)
        result = await policy.check("t1")
        service.consume_request.assert_awaited_once_with("t1")
        assert result.allowed is True


class TestQuotaCheckMiddleware:
    @pytest.mark.asyncio
    async def test_passthrough_non_http(self) -> None:
        app = AsyncMock()
        policy = QuotaPolicy(service=MagicMock())
        mw = QuotaCheckMiddleware(app, policy)
        await mw({"type": "websocket"}, MagicMock(), MagicMock())
        app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passthrough_skip(self) -> None:
        app = AsyncMock()
        policy = QuotaPolicy(service=MagicMock())
        mw = QuotaCheckMiddleware(app, policy)
        await mw({"type": "http", "path": "/metrics"}, MagicMock(), MagicMock())
        app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passthrough_no_tenant(self) -> None:
        app = AsyncMock()
        policy = QuotaPolicy(service=MagicMock())
        mw = QuotaCheckMiddleware(app, policy)
        await mw(
            {"type": "http", "path": "/api", "headers": []}, MagicMock(), MagicMock()
        )
        app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_allowed(self) -> None:
        app = AsyncMock()
        service = AsyncMock()
        service.consume_request = AsyncMock(return_value=MagicMock(allowed=True))
        policy = QuotaPolicy(service=service)
        mw = QuotaCheckMiddleware(app, policy)
        scope = {"type": "http", "path": "/api", "headers": [(b"x-tenant-id", b"t1")]}
        await mw(scope, MagicMock(), MagicMock())
        app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_denied(self) -> None:
        app = AsyncMock()
        service = AsyncMock()
        usage = MagicMock()
        usage.reset_minute_at = 60
        usage.reset_day_at = 86400
        service.consume_request = AsyncMock(
            return_value=MagicMock(allowed=False, reason="rpm", usage=usage)
        )
        policy = QuotaPolicy(service=service)
        mw = QuotaCheckMiddleware(app, policy)
        send = AsyncMock()
        scope = {"type": "http", "path": "/api", "headers": [(b"x-tenant-id", b"t1")]}
        await mw(scope, MagicMock(), send)
        app.assert_not_awaited()
        assert send.await_count == 2
        start_call = send.await_args_list[0][0][0]
        assert start_call["status"] == 429
