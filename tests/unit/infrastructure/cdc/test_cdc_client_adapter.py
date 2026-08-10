"""Тесты CDCClientAdapter (Wave 5)."""


from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.backend.infrastructure.cdc.cdc_client_adapter import (
    CDCClientAdapter,
    _client_event_to_source,
)


def test_client_event_to_source() -> None:
    """_client_event_to_source корректно мапит поля."""
    raw = {
        "operation": "INSERT",
        "table": "orders",
        "timestamp": "2026-06-01T12:00:00+00:00",
        "profile": "pg_prod",
        "new": {"id": 1},
        "old": None,
    }
    event = _client_event_to_source(raw)
    assert event.operation == "INSERT"
    assert event.table == "orders"
    assert event.new == {"id": 1}


@pytest.mark.asyncio
async def test_adapter_subscribe_yields_events() -> None:
    """Adapter yield'ит события, полученные через CDCClient callback."""
    client = AsyncMock()
    client.subscribe = AsyncMock(return_value="sub-123")
    client.unsubscribe = AsyncMock(return_value=True)

    adapter = CDCClientAdapter(profile="pg", client=client)

    captured_callback = None

    async def _subscribe(*, callback: object, **kwargs: object) -> str:
        nonlocal captured_callback
        captured_callback = callback
        return "sub-123"

    client.subscribe.side_effect = _subscribe

    async def _producer() -> None:
        await asyncio.sleep(0.01)
        if captured_callback:
            await captured_callback(
                {
                    "operation": "UPDATE",
                    "table": "users",
                    "timestamp": "2026-06-01T12:00:00+00:00",
                    "profile": "pg",
                    "new": {"name": "Alice"},
                    "old": {"name": "Bob"},
                }
            )

    producer_task = asyncio.create_task(_producer())
    events = []
    async for event in adapter.subscribe(tables=["users"]):
        events.append(event)
        await adapter.close()
        break

    await producer_task
    assert len(events) == 1
    assert events[0].operation == "UPDATE"
    assert events[0].table == "users"
    client.unsubscribe.assert_awaited_once_with("sub-123")


# ── M5: CDC adapter DLQ handoff on overflow ──────────────────────────


class _FakeDLQ:
    """Minimal CDCOverflowDLQ implementation для тестов."""

    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send(self, envelope: Any) -> None:
        self.sent.append(envelope)


def _make_event() -> Any:
    """Минимальный валидный CDCEvent для overflow-тестов."""
    from datetime import UTC, datetime

    from src.backend.core.cdc.source import CDCCursor, CDCEvent

    return CDCEvent(
        cursor=CDCCursor(value="0/1", backend="polling", topic="users"),
        operation="INSERT",
        source="pg_prod",
        table="users",
        timestamp=datetime.now(UTC),
        new={"id": 1},
    )


@pytest.mark.asyncio
async def test_dlq_writer_satisfies_protocol() -> None:
    """FakeDLQ must satisfy ``CDCOverflowDLQ`` runtime-checkable Protocol."""
    from src.backend.infrastructure.cdc.cdc_client_adapter import CDCOverflowDLQ

    fake = _FakeDLQ()
    assert isinstance(fake, CDCOverflowDLQ)


@pytest.mark.asyncio
async def test_on_overflow_forwards_to_dlq() -> None:
    """M5: overflow event сериализуется в DLQEnvelope и уходит в DLQ."""
    from src.backend.infrastructure.messaging.dlq_base import DLQReason

    fake = _FakeDLQ()
    adapter = CDCClientAdapter(profile="pg_prod", dlq_writer=fake)
    event = _make_event()

    await adapter._on_overflow(event)

    assert len(fake.sent) == 1
    envelope = fake.sent[0]
    assert envelope.reason == DLQReason.OVERFLOW
    assert envelope.transport == "cdc:pg_prod"
    assert envelope.route_id == "pg_prod.users"
    assert envelope.error_class == "CDCAdapterQueueOverflow"


@pytest.mark.asyncio
async def test_on_overflow_without_dlq_does_not_raise(caplog: Any) -> None:
    """M5: без dlq_writer — pre-M5 поведение (ERROR log + drop)."""
    import logging

    caplog.set_level(logging.ERROR, logger="cdc.cdc_client_adapter")
    adapter = CDCClientAdapter(profile="pg_prod")  # no dlq_writer
    event = _make_event()
    await adapter._on_overflow(event)  # must not raise
    assert "EVENT DROPPED" in caplog.text or "OVERFLOW" in caplog.text


@pytest.mark.asyncio
async def test_on_overflow_dlq_failure_does_not_propagate() -> None:
    """M5: если DLQ сам упал — consumer loop не должен падать."""

    class _FailingDLQ:
        async def send(self, envelope: Any) -> None:
            raise RuntimeError("DLQ down")

    adapter = CDCClientAdapter(profile="pg_prod", dlq_writer=_FailingDLQ())
    event = _make_event()
    # Should not raise — overflow handler swallows DLQ failures.
    await adapter._on_overflow(event)


def test_dlq_envelope_shape() -> None:
    """Smoke-проверка структуры DLQEnvelope (reason, transport, route_id)."""
    from src.backend.infrastructure.cdc.cdc_client_adapter import _to_dlq_envelope
    from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope, DLQReason

    event = _make_event()
    envelope = _to_dlq_envelope(event, profile="pg_prod")
    assert isinstance(envelope, DLQEnvelope)
    assert envelope.reason == DLQReason.OVERFLOW
    assert envelope.metadata["source"] == "pg_prod"
    assert envelope.metadata["table"] == "users"


# Import for type hint in _FakeDLQ (Any in test signatures)
from typing import Any
