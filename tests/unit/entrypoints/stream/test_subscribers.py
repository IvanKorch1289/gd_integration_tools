"""Unit tests for stream subscribers (Redis + RabbitMQ DSL actions)."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.di.providers import http, workflow
from src.backend.infrastructure.messaging.dlq import InMemoryDLQWriter


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
    """Load subscribers module with faked dependencies + InMemoryDLQWriter."""
    fake_redis_router = FakeRouter("redis")
    fake_rabbit_router = FakeRouter("rabbit")
    fake_client = MagicMock()
    fake_client.redis_router = fake_redis_router
    fake_client.rabbit_router = fake_rabbit_router

    fake_logger = MagicMock()
    dlq_writer = InMemoryDLQWriter()

    http.set_stream_client_provider(fake_client)
    workflow.set_stream_logger_provider(fake_logger)
    workflow.set_stream_dlq_writer_provider(dlq_writer)

    # Ensure module is not already imported with real dependencies
    for mod_name in list(sys.modules.keys()):
        if mod_name == "src.backend.entrypoints.stream.subscribers":
            del sys.modules[mod_name]

    with patch("src.backend.core.config.settings.settings") as mock_settings:
        mock_settings.redis.get_stream_name.return_value = "dsl-events"
        mock_settings.queue.get_queue_name.return_value = "dsl-actions"
        with patch(
            "src.backend.entrypoints.stream.subscribers.action_handler_registry",
        ) as mock_registry:
            import src.backend.entrypoints.stream.subscribers as subscribers

            yield {
                "module": subscribers,
                "redis_router": fake_redis_router,
                "rabbit_router": fake_rabbit_router,
                "logger": fake_logger,
                "registry": mock_registry,
                "dlq": dlq_writer,
            }

    http.set_stream_client_provider(None)  # type: ignore[arg-type]
    workflow.set_stream_logger_provider(None)  # type: ignore[arg-type]
    workflow.set_stream_dlq_writer_provider(None)  # type: ignore[arg-type]


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
            body={"action": "test.a", "payload": {}}, msg=fake_msg, redis=fake_redis,
        )

        registry.dispatch.assert_awaited_once()
        args = registry.dispatch.call_args[0][0]
        assert args.action == "test.a"
        subscribers_fixture["logger"].info.assert_called()
        assert subscribers_fixture["dlq"].records == []

    @pytest.mark.asyncio
    async def test_invalid_body_enqueues_dlq(self, subscribers_fixture: Any) -> None:
        """cycle-5/D-AUDIT-504: invalid body → DLQ poison message."""
        redis_handler = subscribers_fixture["redis_router"].handlers[0][1]
        registry = subscribers_fixture["registry"]
        registry.dispatch = AsyncMock()

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-invalid-redis"
        fake_redis = MagicMock()

        await redis_handler(body={"bad": "body"}, msg=fake_msg, redis=fake_redis)

        registry.dispatch.assert_not_awaited()
        subscribers_fixture["logger"].error.assert_called()
        dlq = subscribers_fixture["dlq"]
        assert len(dlq.records) == 1
        envelope = dlq.records[0]
        assert envelope.transport == "mq:redis"
        assert envelope.route_id == "dsl-events"
        assert envelope.original_payload == {"bad": "body"}
        assert envelope.metadata["correlation_id"] == "cid-invalid-redis"
        assert "poison_message" in envelope.metadata

    @pytest.mark.asyncio
    async def test_dispatch_exception_enqueues_dlq(
        self, subscribers_fixture: Any,
    ) -> None:
        """cycle-5/D-AUDIT-504: dispatch exception → DLQ poison message."""
        redis_handler = subscribers_fixture["redis_router"].handlers[0][1]
        registry = subscribers_fixture["registry"]
        registry.dispatch = AsyncMock(side_effect=RuntimeError("dispatch err"))

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-dispatch-redis"
        fake_redis = MagicMock()

        await redis_handler(
            body={"action": "test.b", "payload": {}}, msg=fake_msg, redis=fake_redis,
        )

        subscribers_fixture["logger"].error.assert_called()
        dlq = subscribers_fixture["dlq"]
        assert len(dlq.records) == 1
        envelope = dlq.records[0]
        assert envelope.transport == "mq:redis"
        assert envelope.error_class == "RuntimeError"
        assert "dispatch err" in envelope.error_message
        assert envelope.metadata["correlation_id"] == "cid-dispatch-redis"

    @pytest.mark.asyncio
    async def test_dispatch_exception_correlation_id_none(
        self, subscribers_fixture: Any,
    ) -> None:
        """cycle-5/D-AUDIT-504: correlation_id=None не падает, DLQ записан."""
        redis_handler = subscribers_fixture["redis_router"].handlers[0][1]
        registry = subscribers_fixture["registry"]
        registry.dispatch = AsyncMock(side_effect=ValueError("boom"))

        fake_msg = MagicMock()
        fake_msg.correlation_id = None
        fake_redis = MagicMock()

        await redis_handler(
            body={"action": "test.x", "payload": {}}, msg=fake_msg, redis=fake_redis,
        )

        dlq = subscribers_fixture["dlq"]
        assert len(dlq.records) == 1
        assert dlq.records[0].metadata["correlation_id"] is None


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
        assert subscribers_fixture["dlq"].records == []

    @pytest.mark.asyncio
    async def test_invalid_body_enqueues_dlq(self, subscribers_fixture: Any) -> None:
        """cycle-5/D-AUDIT-504: invalid body → DLQ poison message (rabbit)."""
        rabbit_handler = subscribers_fixture["rabbit_router"].handlers[0][1]
        registry = subscribers_fixture["registry"]
        registry.dispatch = AsyncMock()

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-invalid-rabbit"

        await rabbit_handler(body={"bad": "body"}, msg=fake_msg)

        registry.dispatch.assert_not_awaited()
        subscribers_fixture["logger"].error.assert_called()
        dlq = subscribers_fixture["dlq"]
        assert len(dlq.records) == 1
        envelope = dlq.records[0]
        assert envelope.transport == "mq:rabbit"
        assert envelope.route_id == "dsl-actions"
        assert envelope.metadata["correlation_id"] == "cid-invalid-rabbit"

    @pytest.mark.asyncio
    async def test_dispatch_exception_enqueues_dlq(
        self, subscribers_fixture: Any,
    ) -> None:
        """cycle-5/D-AUDIT-504: dispatch exception → DLQ poison message (rabbit)."""
        rabbit_handler = subscribers_fixture["rabbit_router"].handlers[0][1]
        registry = subscribers_fixture["registry"]
        registry.dispatch = AsyncMock(side_effect=ValueError("fail"))

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-dispatch-rabbit"

        await rabbit_handler(body={"action": "test.d", "payload": {}}, msg=fake_msg)

        subscribers_fixture["logger"].error.assert_called()
        dlq = subscribers_fixture["dlq"]
        assert len(dlq.records) == 1
        envelope = dlq.records[0]
        assert envelope.transport == "mq:rabbit"
        assert envelope.error_class == "ValueError"
        assert "fail" in envelope.error_message


class TestSubscribersDLQWriterNotConfigured:
    """cycle-5/D-AUDIT-504: DLQ writer=None → log warning (fail-loud signal)."""

    @pytest.fixture
    def no_dlq_fixture(self) -> Any:
        fake_redis_router = FakeRouter("redis")
        fake_rabbit_router = FakeRouter("rabbit")
        fake_client = MagicMock()
        fake_client.redis_router = fake_redis_router
        fake_client.rabbit_router = fake_rabbit_router
        fake_logger = MagicMock()

        http.set_stream_client_provider(fake_client)
        workflow.set_stream_logger_provider(fake_logger)
        workflow.set_stream_dlq_writer_provider(None)

        for mod_name in list(sys.modules.keys()):
            if mod_name == "src.backend.entrypoints.stream.subscribers":
                del sys.modules[mod_name]

        with patch("src.backend.core.config.settings.settings") as mock_settings:
            mock_settings.redis.get_stream_name.return_value = "dsl-events"
            mock_settings.queue.get_queue_name.return_value = "dsl-actions"
            with patch(
                "src.backend.entrypoints.stream.subscribers.action_handler_registry",
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
        workflow.set_stream_dlq_writer_provider(None)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_no_dlq_writer_logs_warning(self, no_dlq_fixture: Any) -> None:
        """При отсутствии DLQ writer'а handler логирует warning (fail-loud)."""
        redis_handler = no_dlq_fixture["redis_router"].handlers[0][1]
        registry = no_dlq_fixture["registry"]
        registry.dispatch = AsyncMock(side_effect=RuntimeError("dispatch err"))

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-no-dlq"
        fake_redis = MagicMock()

        await redis_handler(
            body={"action": "test.z", "payload": {}}, msg=fake_msg, redis=fake_redis,
        )

        no_dlq_fixture["logger"].warning.assert_called()
        no_dlq_fixture["logger"].error.assert_called()
