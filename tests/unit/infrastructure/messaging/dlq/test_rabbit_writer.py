"""Unit tests for RabbitDLQWriter (msgspec migration)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.messaging.dlq.rabbit_writer import RabbitDLQWriter
from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope, DLQReason


@pytest.fixture
def envelope() -> DLQEnvelope:
    return DLQEnvelope(
        dlq_id="rabbit-dlq-1",
        transport="soap",
        trace_id="trace-1",
        tenant_id="tenant-1",
        error_class="ConnectionError",
        error_message="conn refused",
        reason=DLQReason.RETRIES_EXHAUSTED,
    )


@pytest.fixture
def channel() -> MagicMock:
    ch = MagicMock()
    ch.default_exchange = AsyncMock()
    ch.get_exchange = AsyncMock(return_value=AsyncMock())
    return ch


class TestRabbitDLQWriter:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_default_exchange(
        self, channel: MagicMock, envelope: DLQEnvelope
    ) -> None:
        writer = RabbitDLQWriter(channel=channel)
        await writer.write(envelope)

        channel.default_exchange.publish.assert_awaited_once()
        args = channel.default_exchange.publish.call_args
        msg = args.args[0]
        assert msg.body is not None
        payload = json.loads(msg.body)
        assert payload["dlq_id"] == "rabbit-dlq-1"
        assert args.kwargs["routing_key"] == "dlq.soap"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_named_exchange(
        self, channel: MagicMock, envelope: DLQEnvelope
    ) -> None:
        writer = RabbitDLQWriter(channel=channel, exchange_name="dlx")
        await writer.write(envelope)

        channel.get_exchange.assert_awaited_once_with("dlx")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_propagates_exception(
        self, channel: MagicMock, envelope: DLQEnvelope
    ) -> None:
        channel.default_exchange.publish.side_effect = RuntimeError("rabbit down")
        writer = RabbitDLQWriter(channel=channel)

        with pytest.raises(RuntimeError, match="rabbit down"):
            await writer.write(envelope)
