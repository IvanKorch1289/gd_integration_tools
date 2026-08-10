"""Integration tests для MQ subscribers DLQ handoff (cycle-5/D-AUDIT-504).

Тесты верифицируют end-to-end flow без mock'ов внутренних компонент:
реальный :class:`InMemoryDLQWriter` + реальный :class:`FanoutDLQWriter`
+ реальная :func:`enqueue_mq_poison_message`. Mock'аются только DI-провайдеры
для FastStream router'а и logger'а.

Без testcontainers (MQ не поднимается): тесты изолированы через
``workflow.set_stream_dlq_writer_provider`` (override).
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.di.providers import http, workflow
from src.backend.core.messaging.dlq import DLQEnvelope, DLQReason
from src.backend.infrastructure.messaging.dlq import FanoutDLQWriter, InMemoryDLQWriter


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
def integration_fixture() -> Any:
    """Load subscribers + invoker_subscribers with real FanoutDLQWriter."""
    fake_redis_router = FakeRouter("redis")
    fake_rabbit_router = FakeRouter("rabbit")
    fake_client = MagicMock()
    fake_client.redis_router = fake_redis_router
    fake_client.rabbit_router = fake_rabbit_router

    fake_logger = MagicMock()

    # Real DLQ writers (integration: не mock).
    primary_writer = InMemoryDLQWriter()
    secondary_writer = InMemoryDLQWriter()
    fanout_writer = FanoutDLQWriter(writers=[primary_writer, secondary_writer])

    http.set_stream_client_provider(fake_client)
    workflow.set_stream_logger_provider(fake_logger)
    workflow.set_stream_dlq_writer_provider(fanout_writer)

    for mod_name in list(sys.modules.keys()):
        if mod_name in {
            "src.backend.entrypoints.stream.subscribers",
            "src.backend.entrypoints.stream.invoker_subscribers",
        }:
            del sys.modules[mod_name]

    with patch("src.backend.core.config.settings.settings") as mock_settings:
        mock_settings.redis.get_stream_name.return_value = "dsl-events"
        mock_settings.queue.get_queue_name.return_value = "dsl-actions"
        with (
            patch(
                "src.backend.services.execution.invoker._deserialize_request"
            ) as mock_deser,
            patch(
                "src.backend.services.execution.invoker.get_invoker"
            ) as mock_get_invoker,
            patch(
                "src.backend.entrypoints.stream.subscribers.action_handler_registry"
            ) as mock_registry,
        ):
            import src.backend.entrypoints.stream.invoker_subscribers as invoker_mod
            import src.backend.entrypoints.stream.subscribers as subscribers_mod

            yield {
                "subscribers_module": subscribers_mod,
                "invoker_module": invoker_mod,
                "redis_router": fake_redis_router,
                "rabbit_router": fake_rabbit_router,
                "logger": fake_logger,
                "deserialize": mock_deser,
                "get_invoker": mock_get_invoker,
                "registry": mock_registry,
                "primary_dlq": primary_writer,
                "secondary_dlq": secondary_writer,
                "fanout_dlq": fanout_writer,
            }

    http.set_stream_client_provider(None)  # type: ignore[arg-type]
    workflow.set_stream_logger_provider(None)  # type: ignore[arg-type]
    workflow.set_stream_dlq_writer_provider(None)  # type: ignore[arg-type]


class TestSubscribersFanoutDLQIntegration:
    """cycle-5/D-AUDIT-504: real FanoutDLQWriter получает все poison messages."""

    @pytest.mark.asyncio
    async def test_redis_invalid_body_writes_to_both_writers(
        self, integration_fixture: Any
    ) -> None:
        redis_handler = integration_fixture["subscribers_module"].handle_universal_redis_action
        registry = integration_fixture["registry"]
        registry.dispatch = AsyncMock()

        fake_msg = MagicMock()
        fake_msg.correlation_id = "fanout-cid-redis"
        fake_redis = MagicMock()

        await redis_handler(body={"bad": "body"}, msg=fake_msg, redis=fake_redis)

        primary = integration_fixture["primary_dlq"]
        secondary = integration_fixture["secondary_dlq"]
        assert len(primary.records) == 1
        assert len(secondary.records) == 1
        assert primary.records[0].dlq_id == secondary.records[0].dlq_id

    @pytest.mark.asyncio
    async def test_rabbit_dispatch_exception_writes_to_both_writers(
        self, integration_fixture: Any
    ) -> None:
        rabbit_handler = integration_fixture["subscribers_module"].handle_universal_rabbit_action
        registry = integration_fixture["registry"]
        registry.dispatch = AsyncMock(side_effect=ValueError("dispatch failed"))

        fake_msg = MagicMock()
        fake_msg.correlation_id = "fanout-cid-rabbit"

        await rabbit_handler(body={"action": "x", "payload": {}}, msg=fake_msg)

        primary = integration_fixture["primary_dlq"]
        secondary = integration_fixture["secondary_dlq"]
        assert len(primary.records) == 1
        assert len(secondary.records) == 1
        assert primary.records[0].error_class == "ValueError"
        assert secondary.records[0].error_class == "ValueError"


class TestInvokerSubscribersFanoutDLQIntegration:
    """cycle-5/D-AUDIT-504: real FanoutDLQWriter для invoker pathway."""

    @pytest.mark.asyncio
    async def test_redis_invalid_body_writes_to_both_writers(
        self, integration_fixture: Any
    ) -> None:
        handler = integration_fixture["invoker_module"].handle_redis_invocation
        integration_fixture["deserialize"].side_effect = ValueError("bad body")

        fake_msg = MagicMock()
        fake_msg.correlation_id = "inv-cid-redis"
        fake_redis = MagicMock()

        await handler(body={"bad": "body"}, msg=fake_msg, redis=fake_redis)

        primary = integration_fixture["primary_dlq"]
        secondary = integration_fixture["secondary_dlq"]
        assert len(primary.records) == 1
        assert len(secondary.records) == 1
        assert primary.records[0].reason == DLQReason.UNEXPECTED

    @pytest.mark.asyncio
    async def test_rabbit_invoker_raises_writes_to_both_writers(
        self, integration_fixture: Any
    ) -> None:
        handler = integration_fixture["invoker_module"].handle_rabbit_invocation
        fake_request = MagicMock()
        fake_request.action = "x.y"
        fake_request.invocation_id = "inv-fanout"
        fake_request.metadata = {}  # Explicit dict (не MagicMock)
        integration_fixture["deserialize"].return_value = fake_request

        fake_invoker = MagicMock()
        fake_invoker.invoke = AsyncMock(side_effect=RuntimeError("invoke failed"))
        integration_fixture["get_invoker"].return_value = fake_invoker

        fake_msg = MagicMock()
        fake_msg.correlation_id = "inv-cid-rabbit"

        await handler(body={"action": "x.y"}, msg=fake_msg)

        primary = integration_fixture["primary_dlq"]
        secondary = integration_fixture["secondary_dlq"]
        assert len(primary.records) == 1
        assert len(secondary.records) == 1
        envelope = primary.records[0]
        assert envelope.error_class == "RuntimeError"
        assert "invoke failed" in envelope.error_message
        assert envelope.metadata["correlation_id"] == "inv-cid-rabbit"
        assert "poison_message" in envelope.metadata


class TestEnvelopeStructureIntegration:
    """cycle-5/D-AUDIT-504: structure envelope соответствует :class:`DLQEnvelope`."""

    @pytest.mark.asyncio
    async def test_envelope_has_required_fields(
        self, integration_fixture: Any
    ) -> None:
        redis_handler = integration_fixture["subscribers_module"].handle_universal_redis_action
        registry = integration_fixture["registry"]
        registry.dispatch = AsyncMock(side_effect=RuntimeError("dispatch boom"))

        fake_msg = MagicMock()
        fake_msg.correlation_id = "struct-cid"
        fake_redis = MagicMock()

        body = {"action": "test.struct", "payload": {"key": "value"}}
        await redis_handler(body=body, msg=fake_msg, redis=fake_redis)

        primary = integration_fixture["primary_dlq"]
        assert len(primary.records) == 1
        envelope = primary.records[0]
        assert isinstance(envelope, DLQEnvelope)
        assert envelope.transport == "mq:redis"
        assert envelope.route_id == "dsl-events"
        assert envelope.error_class == "RuntimeError"
        assert envelope.error_message == "dispatch boom"
        assert envelope.reason == DLQReason.UNEXPECTED
        assert envelope.original_payload == body
        assert envelope.metadata["correlation_id"] == "struct-cid"
        assert "poison_message" in envelope.metadata
        assert envelope.dlq_id  # UUID сгенерирован
