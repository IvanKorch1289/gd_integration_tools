"""Unit tests for KafkaDLQWriter (msgspec migration)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.messaging.dlq.kafka_writer import KafkaDLQWriter
from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope, DLQReason


@pytest.fixture
def envelope() -> DLQEnvelope:
    return DLQEnvelope(
        dlq_id="test-dlq-1",
        transport="http",
        trace_id="trace-1",
        tenant_id="tenant-1",
        route_id="route-1",
        original_payload={"body": "value"},
        error_class="ConnectTimeout",
        error_message="connection failed",
        reason=DLQReason.TIMEOUT,
        retry_count=2,
        metadata={"upstream": "http://example.com"},
    )


@pytest.fixture
def producer() -> AsyncMock:
    return AsyncMock()


class TestKafkaDLQWriter:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_success(self, producer: AsyncMock, envelope: DLQEnvelope) -> None:
        writer = KafkaDLQWriter(producer=producer)
        await writer.write(envelope)

        producer.send_and_wait.assert_awaited_once()
        call_args = producer.send_and_wait.call_args
        assert call_args.args[0] == "dlq.http"
        assert call_args.kwargs["key"] == b"test-dlq-1"
        payload = json.loads(call_args.kwargs["value"])
        assert payload["dlq_id"] == "test-dlq-1"
        assert payload["transport"] == "http"
        assert payload["reason"] == "timeout"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_custom_topic_prefix(self, producer: AsyncMock, envelope: DLQEnvelope) -> None:
        writer = KafkaDLQWriter(producer=producer, topic_prefix="dead.")
        envelope.transport = "soap"
        await writer.write(envelope)

        producer.send_and_wait.assert_awaited_once()
        assert producer.send_and_wait.call_args.args[0] == "dead.soap"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_propagates_exception(self, producer: AsyncMock, envelope: DLQEnvelope) -> None:
        producer.send_and_wait.side_effect = RuntimeError("kafka down")
        writer = KafkaDLQWriter(producer=producer)

        with pytest.raises(RuntimeError, match="kafka down"):
            await writer.write(envelope)

    @pytest.mark.unit
    def test_default_serialize_returns_bytes(self, envelope: DLQEnvelope) -> None:
        raw = KafkaDLQWriter._default_serialize(envelope)
        assert isinstance(raw, bytes)
        parsed = json.loads(raw)
        assert parsed["dlq_id"] == "test-dlq-1"
        assert parsed["reason"] == "timeout"
        # datetime должен быть сериализован в ISO-строку
        assert isinstance(parsed["first_failed_at"], str)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_custom_serializer(self, producer: AsyncMock, envelope: DLQEnvelope) -> None:
        custom = MagicMock(return_value=b"custom-payload")
        writer = KafkaDLQWriter(producer=producer, serializer=custom)
        await writer.write(envelope)

        custom.assert_called_once_with(envelope)
        assert producer.send_and_wait.call_args.kwargs["value"] == b"custom-payload"
