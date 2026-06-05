"""Additional unit tests for global_ratelimit middleware (coverage push v5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.entrypoints.middlewares.global_ratelimit import (
    FakeRateLimitChecker,
    GlobalRateLimitMiddleware,
    RateLimitConfig,
    RedisRateLimitChecker,
    tenant_aware_identifier,
)


class TestTenantAwareIdentifier:
    """Tests for tenant_aware_identifier."""

    def test_tenant_header(self) -> None:
        scope = {"headers": [(b"x-tenant-id", b"acme")], "client": ("1.2.3.4", 1234)}
        assert tenant_aware_identifier(scope) == "tenant:acme"

    def test_user_header(self) -> None:
        scope = {"headers": [(b"x-user-id", b"u1")], "client": ("1.2.3.4", 1234)}
        assert tenant_aware_identifier(scope) == "user:u1"

    def test_ip_fallback(self) -> None:
        scope = {"headers": [], "client": ("1.2.3.4", 1234)}
        assert tenant_aware_identifier(scope) == "ip:1.2.3.4"

    def test_missing_client(self) -> None:
        scope = {"headers": [], "client": None}
        assert tenant_aware_identifier(scope) == "ip:-"


class TestRedisRateLimitChecker:
    """Tests for RedisRateLimitChecker."""

    @pytest.fixture
    def redis(self) -> MagicMock:
        return AsyncMock()

    @pytest.fixture
    def checker(self, redis: MagicMock) -> RedisRateLimitChecker:
        return RedisRateLimitChecker(redis, max_per_window=5, window_seconds=10.0)

    @pytest.mark.asyncio
    async def test_allowed(self, checker: RedisRateLimitChecker, redis: MagicMock) -> None:
        redis.incr.return_value = 1
        allowed, remaining, retry = await checker.check("ip1")
        assert allowed is True
        assert remaining == 4
        redis.expire.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_denied(self, checker: RedisRateLimitChecker, redis: MagicMock) -> None:
        redis.incr.return_value = 6
        allowed, remaining, retry = await checker.check("ip1")
        assert allowed is False
        assert remaining == 0
        assert retry == 10

    @pytest.mark.asyncio
    async def test_fail_open(self, checker: RedisRateLimitChecker, redis: MagicMock) -> None:
        redis.incr.side_effect = RuntimeError("redis down")
        allowed, remaining, retry = await checker.check("ip1")
        assert allowed is True
        assert remaining == 5

    @pytest.mark.asyncio
    async def test_route_override_found(self, checker: RedisRateLimitChecker, redis: MagicMock) -> None:
        checker._route_overrides_hash = "overrides"
        redis.hgetall.return_value = {b"/api": b"10:60"}
        result = await checker.check_route_override("/api/v1/users")
        assert isinstance(result, RateLimitConfig)
        assert result.max_per_window == 10
        assert result.window_seconds == 60.0

    @pytest.mark.asyncio
    async def test_route_override_no_hash(self, checker: RedisRateLimitChecker) -> None:
        assert await checker.check_route_override("/any") is None

    @pytest.mark.asyncio
    async def test_route_override_invalid_format(self, checker: RedisRateLimitChecker, redis: MagicMock) -> None:
        checker._route_overrides_hash = "overrides"
        redis.hgetall.return_value = {b"/api": b"bad"}
        assert await checker.check_route_override("/api") is None

    @pytest.mark.asyncio
    async def test_route_override_fail_open(self, checker: RedisRateLimitChecker, redis: MagicMock) -> None:
        checker._route_overrides_hash = "overrides"
        redis.hgetall.side_effect = RuntimeError("redis down")
        assert await checker.check_route_override("/api") is None


class _RecordingApp:
    """Stub-ASGI приложение, фиксирующее вызов."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope, receive, send) -> None:
        self.called = True


async def _empty_receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


class TestGlobalRateLimitMiddlewareExtra:
    """Additional tests for GlobalRateLimitMiddleware."""

    @pytest.mark.asyncio
    async def test_per_route_checker(self) -> None:
        inner = _RecordingApp()
        route_checker = FakeRateLimitChecker(max_per_window=1, window_seconds=60.0)
        await route_checker.check("ip:1.2.3.4")  # exhaust
        mw = GlobalRateLimitMiddleware(
            inner,
            checker=FakeRateLimitChecker(max_per_window=100, window_seconds=60.0),
            feature_enabled=lambda: True,
            route_checkers={"/api": route_checker},
        )
        send = AsyncMock()
        await mw(
            {"type": "http", "path": "/api/v1", "headers": [], "client": ("1.2.3.4", 0)},
            _empty_receive,
            send,
        )
        assert inner.called is False
        start_call = [c for c in send.await_args_list if c.args[0]["type"] == "http.response.start"][0]
        assert start_call.args[0]["status"] == 429
