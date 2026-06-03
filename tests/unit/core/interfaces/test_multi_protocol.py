"""Tests for multi_protocol interfaces."""

from __future__ import annotations

from typing import Any

from src.backend.core.interfaces.multi_protocol import (
    CDCClientProtocol,
    ExpressBotClientProtocol,
    ExpressMetricsRecorderProtocol,
    HealthCheckServiceProtocol,
    LoggerProtocol,
    MongoExpressDialogStoreProtocol,
    MongoExpressSessionStoreProtocol,
    RateLimiterProtocol,
    RedisCursorProtocol,
    RedisHashProtocol,
    RedisPubSubProtocol,
    RedisSetProtocol,
    SLOTrackerProtocol,
    StreamClientProtocol,
    VaultRefresherProtocol,
)


class TestRateLimiterProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            async def check(self, identifier: str, policy: Any) -> dict[str, Any]:
                return {}

        assert isinstance(Impl(), RateLimiterProtocol)

    def test_missing_method_fails(self) -> None:
        class Bad:
            pass

        assert not isinstance(Bad(), RateLimiterProtocol)


class TestRedisHashProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            async def set(self, field: str, value: Any) -> None:
                pass

            async def get(self, field: str) -> Any:
                return None

            async def delete(self, field: str) -> bool:
                return True

            async def all(self) -> dict[str, Any]:
                return {}

        assert isinstance(Impl(), RedisHashProtocol)


class TestRedisSetProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            async def add(self, *members: str) -> int:
                return 0

            async def remove(self, *members: str) -> int:
                return 0

            async def members(self) -> set[str]:
                return set()

            async def contains(self, member: str) -> bool:
                return False

        assert isinstance(Impl(), RedisSetProtocol)


class TestRedisCursorProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            async def get(self) -> Any:
                return None

            async def set(self, value: Any) -> bool:
                return True

        assert isinstance(Impl(), RedisCursorProtocol)


class TestRedisPubSubProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            async def publish(self, message: Any) -> int:
                return 0

            async def subscribe(self) -> Any:
                pass

        assert isinstance(Impl(), RedisPubSubProtocol)


class TestCDCClientProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            async def subscribe(
                self, *, profile: str, tables: list[str], target_action: str | None = None
            ) -> str:
                return ""

            async def unsubscribe(self, subscription_id: str) -> bool:
                return True

            def list_subscriptions(self) -> list[dict[str, Any]]:
                return []

        assert isinstance(Impl(), CDCClientProtocol)


class TestVaultRefresherProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            async def resolve(self, ref: str) -> str:
                return ""

        assert isinstance(Impl(), VaultRefresherProtocol)


class TestLoggerProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
                pass

            def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
                pass

            def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
                pass

            def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
                pass

        assert isinstance(Impl(), LoggerProtocol)


class TestMongoExpressDialogStoreProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            async def append_message(
                self,
                *,
                session_id: str,
                role: str,
                body: str,
                bot_id: str | None = None,
                group_chat_id: str | None = None,
                user_huid: str | None = None,
                sync_id: str | None = None,
            ) -> None:
                pass

        assert isinstance(Impl(), MongoExpressDialogStoreProtocol)


class TestMongoExpressSessionStoreProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            async def ping(self, session_id: str) -> Any:
                return None

        assert isinstance(Impl(), MongoExpressSessionStoreProtocol)


class TestExpressMetricsRecorderProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            def __call__(self, bot: str, command: str) -> None:
                pass

        assert isinstance(Impl(), ExpressMetricsRecorderProtocol)


class TestStreamClientProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            @property
            def redis_router(self) -> Any:
                return None

            @property
            def rabbit_router(self) -> Any:
                return None

        assert isinstance(Impl(), StreamClientProtocol)


class TestExpressBotClientProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            async def send_message(self, message: Any, sync: bool = False) -> str:
                return ""

        assert isinstance(Impl(), ExpressBotClientProtocol)


class TestHealthCheckServiceProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            async def check_all_services(self) -> dict[str, Any]:
                return {}

        assert isinstance(Impl(), HealthCheckServiceProtocol)


class TestSLOTrackerProtocol:
    def test_is_runtime_checkable(self) -> None:
        class Impl:
            def get_report(self) -> dict[str, Any]:
                return {}

        assert isinstance(Impl(), SLOTrackerProtocol)
