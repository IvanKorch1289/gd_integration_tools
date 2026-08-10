"""Unit tests for invoker stream subscribers (Redis + RabbitMQ)."""

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
def invoker_fixture() -> Any:
    """Load invoker_subscribers module with faked deps + InMemoryDLQWriter."""
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

    for mod_name in list(sys.modules.keys()):
        if mod_name == "src.backend.entrypoints.stream.invoker_subscribers":
            del sys.modules[mod_name]

    with patch("src.backend.core.config.settings.settings") as mock_settings:
        mock_settings.redis.get_stream_name.return_value = "invocations-in"
        mock_settings.queue.get_queue_name.return_value = "invocations-in"
        with (
            patch(
                "src.backend.services.execution.invoker._deserialize_request",
            ) as mock_deser,
            patch(
                "src.backend.services.execution.invoker.get_invoker",
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
                "dlq": dlq_writer,
            }

    http.set_stream_client_provider(None)  # type: ignore[arg-type]
    workflow.set_stream_logger_provider(None)  # type: ignore[arg-type]
    workflow.set_stream_dlq_writer_provider(None)  # type: ignore[arg-type]


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
        assert invoker_fixture["dlq"].records == []

    @pytest.mark.asyncio
    async def test_invalid_body_enqueues_dlq(self, invoker_fixture: Any) -> None:
        """cycle-5/D-AUDIT-504: invalid body → DLQ poison message."""
        handler = invoker_fixture["redis_router"].handlers[0][1]
        invoker_fixture["deserialize"].side_effect = ValueError("bad body")

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-redis-invalid"
        fake_redis = MagicMock()

        await handler(body={"bad": "body"}, msg=fake_msg, redis=fake_redis)

        invoker_fixture["logger"].warning.assert_called()
        invoker_fixture["get_invoker"].assert_not_called()
        dlq = invoker_fixture["dlq"]
        assert len(dlq.records) == 1
        envelope = dlq.records[0]
        assert envelope.transport == "mq:redis"
        assert envelope.route_id == "invocations-in"
        assert envelope.error_class == "ValueError"
        assert "bad body" in envelope.error_message
        assert envelope.metadata["correlation_id"] == "cid-redis-invalid"

    @pytest.mark.asyncio
    async def test_invoker_raises_enqueues_dlq(self, invoker_fixture: Any) -> None:
        """cycle-5/D-AUDIT-504: invoker.invoke raises → DLQ poison message."""
        handler = invoker_fixture["redis_router"].handlers[0][1]
        fake_request = MagicMock()
        fake_request.action = "a.c"
        fake_request.invocation_id = "inv-2"
        invoker_fixture["deserialize"].return_value = fake_request

        fake_invoker = MagicMock()
        fake_invoker.invoke = AsyncMock(side_effect=Exception("invoke err"))
        invoker_fixture["get_invoker"].return_value = fake_invoker

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-redis-invoker-raise"
        fake_redis = MagicMock()

        await handler(body={"action": "a.c"}, msg=fake_msg, redis=fake_redis)

        fake_invoker.invoke.assert_awaited_once_with(fake_request)
        invoker_fixture["logger"].exception.assert_called()
        dlq = invoker_fixture["dlq"]
        assert len(dlq.records) == 1
        envelope = dlq.records[0]
        assert envelope.transport == "mq:redis"
        assert envelope.error_class == "Exception"
        assert "invoke err" in envelope.error_message
        assert envelope.metadata["correlation_id"] == "cid-redis-invoker-raise"
        assert "poison_message" in envelope.metadata


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
        assert invoker_fixture["dlq"].records == []

    @pytest.mark.asyncio
    async def test_invalid_body_enqueues_dlq(self, invoker_fixture: Any) -> None:
        """cycle-5/D-AUDIT-504: invalid body → DLQ poison message (rabbit)."""
        handler = invoker_fixture["rabbit_router"].handlers[0][1]
        invoker_fixture["deserialize"].side_effect = KeyError("action")

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-rabbit-invalid"

        await handler(body={}, msg=fake_msg)

        invoker_fixture["logger"].warning.assert_called()
        dlq = invoker_fixture["dlq"]
        assert len(dlq.records) == 1
        envelope = dlq.records[0]
        assert envelope.transport == "mq:rabbit"
        assert envelope.route_id == "invocations-in"
        assert envelope.error_class == "KeyError"
        assert envelope.metadata["correlation_id"] == "cid-rabbit-invalid"

    @pytest.mark.asyncio
    async def test_invoker_raises_enqueues_dlq(self, invoker_fixture: Any) -> None:
        """cycle-5/D-AUDIT-504: invoker.invoke raises → DLQ poison message (rabbit)."""
        handler = invoker_fixture["rabbit_router"].handlers[0][1]
        fake_request = MagicMock()
        fake_request.action = "a.e"
        fake_request.invocation_id = "inv-4"
        invoker_fixture["deserialize"].return_value = fake_request

        fake_invoker = MagicMock()
        fake_invoker.invoke = AsyncMock(side_effect=RuntimeError("boom"))
        invoker_fixture["get_invoker"].return_value = fake_invoker

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-rabbit-raise"

        await handler(body={"action": "a.e"}, msg=fake_msg)

        invoker_fixture["logger"].exception.assert_called()
        dlq = invoker_fixture["dlq"]
        assert len(dlq.records) == 1
        envelope = dlq.records[0]
        assert envelope.transport == "mq:rabbit"
        assert envelope.error_class == "RuntimeError"
        assert "boom" in envelope.error_message


class TestInvokerSubscribersDLQWriterNotConfigured:
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
            if mod_name == "src.backend.entrypoints.stream.invoker_subscribers":
                del sys.modules[mod_name]

        with patch("src.backend.core.config.settings.settings") as mock_settings:
            mock_settings.redis.get_stream_name.return_value = "invocations-in"
            mock_settings.queue.get_queue_name.return_value = "invocations-in"
            with (
                patch(
                    "src.backend.services.execution.invoker._deserialize_request",
                ) as mock_deser,
                patch(
                    "src.backend.services.execution.invoker.get_invoker",
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
        workflow.set_stream_dlq_writer_provider(None)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_no_dlq_writer_logs_warning(self, no_dlq_fixture: Any) -> None:
        """При отсутствии DLQ writer'а handler логирует warning (fail-loud)."""
        handler = no_dlq_fixture["redis_router"].handlers[0][1]
        no_dlq_fixture["deserialize"].side_effect = ValueError("bad body")

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-no-dlq"
        fake_redis = MagicMock()

        await handler(body={"bad": "body"}, msg=fake_msg, redis=fake_redis)

        no_dlq_fixture["logger"].warning.assert_called()

    @pytest.mark.asyncio
    async def test_dlq_writer_failure_logs_error(self, invoker_fixture: Any) -> None:
        """При сбое DLQ.write — log error (poison message не теряется молча)."""
        # Replace the DLQ writer with one whose .write raises.
        broken_writer = MagicMock()
        broken_writer.write = AsyncMock(side_effect=RuntimeError("dlq broken"))
        workflow.set_stream_dlq_writer_provider(broken_writer)

        handler = invoker_fixture["redis_router"].handlers[0][1]
        invoker_fixture["deserialize"].side_effect = ValueError("bad body")

        fake_msg = MagicMock()
        fake_msg.correlation_id = "cid-dlq-broken"
        fake_redis = MagicMock()

        # Should not raise even if DLQ write itself fails.
        await handler(body={"bad": "body"}, msg=fake_msg, redis=fake_redis)

        broken_writer.write.assert_awaited_once()
        invoker_fixture["logger"].error.assert_called()
