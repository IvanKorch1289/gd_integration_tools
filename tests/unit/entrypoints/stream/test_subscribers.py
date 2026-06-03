"""Unit tests for stream subscribers (Redis + RabbitMQ DSL actions)."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.di.providers import http, workflow


class FakeRouter:
    def __init__(self, name: str = "") -> None:
        self.name = name
        self.handlers: list[tuple[str | None, Any]] = []

    def subscriber(self, stream: str | None = None, queue: str | None = None) -> Any:
        def decorator(fn: Any) -> Any:
            self.handlers.append((stream or queue, fn))
            return fn

        return decorator


@pytest.fixture
def subscribers_fixture() -> Any:
    """Load subscribers module with faked dependencies."""
    fake_redis_router = FakeRouter("redis")
    fake_rabbit_router = FakeRouter("rabbit")
    fake_client = MagicMock()
    fake_client.redis_router = fake_redis_router
    fake_client.rabbit_router = fake_rabbit_router

    fake_logger = MagicMock()

    http.set_stream_client_provider(fake_client)
    workflow.set_stream_logger_provider(fake_logger)

    # Ensure module is not already imported with real dependencies
    for mod_name in list(sys.modules.keys()):
        if mod_name == "src.backend.entrypoints.stream.subscribers":
            del sys.modules[mod_name]

    with patch("src.backend.core.config.settings.settings") as mock_settings:
        mock_settings.redis.get_stream_name.return_value = "dsl-events"
        mock_settings.queue.get_queue_name.return_value = "dsl-actions"
        with patch(
            "src.backend.entrypoints.stream.subscribers.action_handler_registry"
        ) as mock_registry:
            import src.backend.entrypoints.stream.subscribers as subscribers

            yield {
                "module": subscribers,
                "redis_router": fake_redis_router,
                "rabbit_router": fake_rabbit_router,
                "logger": fake_logger,
                "registry": mock_registry,
            }

    http.set_stream_client_provider(None)  # type: ignore[arg-type]
    workflow.set_stream_logger_provider(None)  # type: ignore[arg-type]


class TestHandleUniversalRedisAction:
    @pytest.mark.asyncio
    async def test_happy_path(self, subscribers_fixture: Any) -> None:
        redis_handler = subscribers_fixture["redis_router"].handlers[0][1]
        registry = subscribers_fixture["registry"]
        registry.dispatch = AsyncMock(return_value={"ok": True})

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-1"
        fake_redis = MagicMock()

        await redis_handler(
            body={"action": "test.a", "payload": {}}, msg=fake_msg, redis=fake_redis
        )

        registry.dispatch.assert_awaited_once()
        args = registry.dispatch.call_args[0][0]
        assert args.action == "test.a"
        subscribers_fixture["logger"].info.assert_called()

    @pytest.mark.asyncio
    async def test_invalid_body(self, subscribers_fixture: Any) -> None:
        redis_handler = subscribers_fixture["redis_router"].handlers[0][1]
        registry = subscribers_fixture["registry"]
        registry.dispatch = AsyncMock()

        fake_msg = MagicMock()
        fake_msg.correlation_id = None
        fake_redis = MagicMock()

        await redis_handler(body={"bad": "body"}, msg=fake_msg, redis=fake_redis)

        registry.dispatch.assert_not_awaited()
        subscribers_fixture["logger"].error.assert_called()

    @pytest.mark.asyncio
    async def test_dispatch_exception(self, subscribers_fixture: Any) -> None:
        redis_handler = subscribers_fixture["redis_router"].handlers[0][1]
        registry = subscribers_fixture["registry"]
        registry.dispatch = AsyncMock(side_effect=RuntimeError("dispatch err"))

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-2"
        fake_redis = MagicMock()

        await redis_handler(
            body={"action": "test.b", "payload": {}}, msg=fake_msg, redis=fake_redis
        )

        subscribers_fixture["logger"].error.assert_called()


class TestHandleUniversalRabbitAction:
    @pytest.mark.asyncio
    async def test_happy_path(self, subscribers_fixture: Any) -> None:
        rabbit_handler = subscribers_fixture["rabbit_router"].handlers[0][1]
        registry = subscribers_fixture["registry"]
        registry.dispatch = AsyncMock(return_value={"ok": True})

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-3"

        await rabbit_handler(body={"action": "test.c", "payload": {}}, msg=fake_msg)

        registry.dispatch.assert_awaited_once()
        subscribers_fixture["logger"].info.assert_called()

    @pytest.mark.asyncio
    async def test_invalid_body(self, subscribers_fixture: Any) -> None:
        rabbit_handler = subscribers_fixture["rabbit_router"].handlers[0][1]
        registry = subscribers_fixture["registry"]
        registry.dispatch = AsyncMock()

        fake_msg = MagicMock()
        fake_msg.correlation_id = None

        await rabbit_handler(body={"bad": "body"}, msg=fake_msg)

        registry.dispatch.assert_not_awaited()
        subscribers_fixture["logger"].error.assert_called()

    @pytest.mark.asyncio
    async def test_dispatch_exception(self, subscribers_fixture: Any) -> None:
        rabbit_handler = subscribers_fixture["rabbit_router"].handlers[0][1]
        registry = subscribers_fixture["registry"]
        registry.dispatch = AsyncMock(side_effect=ValueError("fail"))

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-4"

        await rabbit_handler(body={"action": "test.d", "payload": {}}, msg=fake_msg)

        subscribers_fixture["logger"].error.assert_called()
