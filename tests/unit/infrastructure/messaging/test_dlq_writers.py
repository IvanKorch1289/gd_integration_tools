"""Unit-тесты DLQ writers (Sprint 9 K2 W1).

Покрывает: InMemoryDLQWriter, FanoutDLQWriter. Реальные backend-ы
(Kafka/Rabbit/NATS/Inbox) тестируются на integration-уровне (см.
``tests/integration/messaging/test_dlq_unified.py``).
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.messaging.dlq import (
    DLQEnvelope,
    DLQReason,
    FanoutDLQWriter,
    InMemoryDLQWriter,
)


@pytest.fixture
def envelope() -> DLQEnvelope:
    return DLQEnvelope(
        transport="http",
        error_class="httpx.ConnectTimeout",
        error_message="timeout to backend",
        reason=DLQReason.TIMEOUT,
    )


@pytest.mark.asyncio
async def test_memory_writer_records_envelope(envelope: DLQEnvelope) -> None:
    writer = InMemoryDLQWriter()
    await writer.write(envelope)
    assert len(writer.records) == 1
    assert writer.records[0].dlq_id == envelope.dlq_id


@pytest.mark.asyncio
async def test_memory_writer_dedup_by_dlq_id(envelope: DLQEnvelope) -> None:
    writer = InMemoryDLQWriter()
    await writer.write(envelope)
    await writer.write(envelope)
    assert len(writer.records) == 1


@pytest.mark.asyncio
async def test_memory_writer_clear(envelope: DLQEnvelope) -> None:
    writer = InMemoryDLQWriter()
    await writer.write(envelope)
    writer.clear()
    assert writer.records == []


@pytest.mark.asyncio
async def test_fanout_success_if_any_writer_succeeds(envelope: DLQEnvelope) -> None:
    good = InMemoryDLQWriter()

    class _BadWriter:
        async def write(self, _env: DLQEnvelope) -> None:
            raise ConnectionError("kafka unreachable")

    fanout = FanoutDLQWriter(writers=[good, _BadWriter()])
    await fanout.write(envelope)
    assert len(good.records) == 1


@pytest.mark.asyncio
async def test_fanout_raises_if_all_failed(envelope: DLQEnvelope) -> None:
    class _BadWriter:
        async def write(self, _env: DLQEnvelope) -> None:
            raise ConnectionError("down")

    fanout = FanoutDLQWriter(writers=[_BadWriter(), _BadWriter()])
    with pytest.raises(ConnectionError):
        await fanout.write(envelope)


@pytest.mark.asyncio
async def test_fanout_require_all_strict(envelope: DLQEnvelope) -> None:
    good = InMemoryDLQWriter()

    class _BadWriter:
        async def write(self, _env: DLQEnvelope) -> None:
            raise RuntimeError("partial failure")

    fanout = FanoutDLQWriter(writers=[good, _BadWriter()], require_all=True)
    with pytest.raises(RuntimeError):
        await fanout.write(envelope)


def test_fanout_rejects_empty_writers() -> None:
    with pytest.raises(ValueError, match="at least one"):
        FanoutDLQWriter(writers=[])
