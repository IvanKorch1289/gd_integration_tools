"""Unit tests for NATSDLQWriter (msgspec migration)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.backend.infrastructure.messaging.dlq.nats_writer import NATSDLQWriter
from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope, DLQReason


@pytest.fixture
def envelope() -> DLQEnvelope:
    return DLQEnvelope(
        dlq_id="nats-dlq-1",
        transport="http",
        trace_id="trace-1",
        tenant_id="tenant-1",
        error_class="TimeoutError",
        error_message="timeout",
        reason=DLQReason.TIMEOUT,
    )


@pytest.fixture
def jetstream() -> AsyncMock:
    return AsyncMock()


class TestNATSDLQWriter:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_success(self, jetstream: AsyncMock, envelope: DLQEnvelope) -> None:
        writer = NATSDLQWriter(jetstream=jetstream)
        await writer.write(envelope)

        jetstream.publish.assert_awaited_once()
        args = jetstream.publish.call_args
        assert args.args[0] == "dlq.http"
        payload = json.loads(args.args[1])
        assert payload["dlq_id"] == "nats-dlq-1"
        assert args.kwargs["headers"]["Nats-Msg-Id"] == "nats-dlq-1"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_custom_prefix(self, jetstream: AsyncMock, envelope: DLQEnvelope) -> None:
        writer = NATSDLQWriter(jetstream=jetstream, subject_prefix="dead.")
        envelope.transport = "grpc"
        await writer.write(envelope)

        assert jetstream.publish.call_args.args[0] == "dead.grpc"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_propagates_exception(self, jetstream: AsyncMock, envelope: DLQEnvelope) -> None:
        jetstream.publish.side_effect = RuntimeError("nats down")
        writer = NATSDLQWriter(jetstream=jetstream)

        with pytest.raises(RuntimeError, match="nats down"):
            await writer.write(envelope)
