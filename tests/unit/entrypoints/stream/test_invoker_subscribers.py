"""Unit tests for invoker stream subscribers (Redis + RabbitMQ)."""

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
def invoker_fixture() -> Any:
    fake_redis_router = FakeRouter("redis")
    fake_rabbit_router = FakeRouter("rabbit")
    fake_client = MagicMock()
    fake_client.redis_router = fake_redis_router
    fake_client.rabbit_router = fake_rabbit_router

    fake_logger = MagicMock()

    http.set_stream_client_provider(fake_client)
    workflow.set_stream_logger_provider(fake_logger)

    for mod_name in list(sys.modules.keys()):
        if mod_name == "src.backend.entrypoints.stream.invoker_subscribers":
            del sys.modules[mod_name]

    with patch("src.backend.core.config.settings.settings") as mock_settings:
        mock_settings.redis.get_stream_name.return_value = "invocations-in"
        mock_settings.queue.get_queue_name.return_value = "invocations-in"
        with (
            patch(
                "src.backend.services.execution.invoker._deserialize_request"
            ) as mock_deser,
            patch(
                "src.backend.services.execution.invoker.get_invoker"
            ) as mock_get_invoker,
        ):
            import src.backend.entrypoints.stream.invoker_subscribers as invoker_subscribers

            yield {
                "module": invoker_subscribers,
                "redis_router": fake_redis_router,
                "rabbit_router": fake_rabbit_router,
                "logger": fake_logger,
                "deserialize": mock_deser,
                "get_invoker": mock_get_invoker,
            }

    http.set_stream_client_provider(None)  # type: ignore[arg-type]
    workflow.set_stream_logger_provider(None)  # type: ignore[arg-type]


class TestHandleRedisInvocation:
    @pytest.mark.asyncio
    async def test_happy_path(self, invoker_fixture: Any) -> None:
        handler = invoker_fixture["redis_router"].handlers[0][1]
        fake_request = MagicMock()
        fake_request.action = "a.b"
        fake_request.invocation_id = "inv-1"
        invoker_fixture["deserialize"].return_value = fake_request

        fake_invoker = MagicMock()
        fake_invoker.invoke = AsyncMock(return_value=MagicMock())
        invoker_fixture["get_invoker"].return_value = fake_invoker

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-1"
        fake_redis = MagicMock()

        await handler(body={"action": "a.b"}, msg=fake_msg, redis=fake_redis)

        invoker_fixture["deserialize"].assert_called_once_with({"action": "a.b"})
        fake_invoker.invoke.assert_awaited_once_with(fake_request)
        invoker_fixture["logger"].info.assert_called()

    @pytest.mark.asyncio
    async def test_invalid_body(self, invoker_fixture: Any) -> None:
        handler = invoker_fixture["redis_router"].handlers[0][1]
        invoker_fixture["deserialize"].side_effect = ValueError("bad body")

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-2"
        fake_redis = MagicMock()

        await handler(body={"bad": "body"}, msg=fake_msg, redis=fake_redis)

        invoker_fixture["logger"].warning.assert_called()
        invoker_fixture["get_invoker"].assert_not_called()

    @pytest.mark.asyncio
    async def test_invoker_raises(self, invoker_fixture: Any) -> None:
        handler = invoker_fixture["redis_router"].handlers[0][1]
        fake_request = MagicMock()
        fake_request.action = "a.c"
        fake_request.invocation_id = "inv-2"
        invoker_fixture["deserialize"].return_value = fake_request

        fake_invoker = MagicMock()
        fake_invoker.invoke = AsyncMock(side_effect=Exception("invoke err"))
        invoker_fixture["get_invoker"].return_value = fake_invoker

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-3"
        fake_redis = MagicMock()

        await handler(body={"action": "a.c"}, msg=fake_msg, redis=fake_redis)

        fake_invoker.invoke.assert_awaited_once_with(fake_request)
        invoker_fixture["logger"].exception.assert_called()


class TestHandleRabbitInvocation:
    @pytest.mark.asyncio
    async def test_happy_path(self, invoker_fixture: Any) -> None:
        handler = invoker_fixture["rabbit_router"].handlers[0][1]
        fake_request = MagicMock()
        fake_request.action = "a.d"
        fake_request.invocation_id = "inv-3"
        invoker_fixture["deserialize"].return_value = fake_request

        fake_invoker = MagicMock()
        fake_invoker.invoke = AsyncMock(return_value=MagicMock())
        invoker_fixture["get_invoker"].return_value = fake_invoker

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-4"

        await handler(body={"action": "a.d"}, msg=fake_msg)

        invoker_fixture["deserialize"].assert_called_once_with({"action": "a.d"})
        fake_invoker.invoke.assert_awaited_once_with(fake_request)
        invoker_fixture["logger"].info.assert_called()

    @pytest.mark.asyncio
    async def test_invalid_body(self, invoker_fixture: Any) -> None:
        handler = invoker_fixture["rabbit_router"].handlers[0][1]
        invoker_fixture["deserialize"].side_effect = KeyError("action")

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-5"

        await handler(body={}, msg=fake_msg)

        invoker_fixture["logger"].warning.assert_called()

    @pytest.mark.asyncio
    async def test_invoker_raises(self, invoker_fixture: Any) -> None:
        handler = invoker_fixture["rabbit_router"].handlers[0][1]
        fake_request = MagicMock()
        fake_request.action = "a.e"
        fake_request.invocation_id = "inv-4"
        invoker_fixture["deserialize"].return_value = fake_request

        fake_invoker = MagicMock()
        fake_invoker.invoke = AsyncMock(side_effect=RuntimeError("boom"))
        invoker_fixture["get_invoker"].return_value = fake_invoker

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-6"

        await handler(body={"action": "a.e"}, msg=fake_msg)

        invoker_fixture["logger"].exception.assert_called()
