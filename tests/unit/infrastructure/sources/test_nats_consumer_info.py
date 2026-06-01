"""Unit-тесты NATSJetStreamSource.fetch_consumer_info + admin endpoint (S13 K3 W5)."""

# ruff: noqa: S101

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def source():
    from src.backend.infrastructure.sources.nats_jetstream import (
        NATSJetStreamSource,
    )

    src = NATSJetStreamSource(
        subject="orders.created", stream="ORDERS", durable="orders-consumer"
    )
    return src


@pytest.mark.asyncio
async def test_fetch_consumer_info_disconnected(source) -> None:
    info = await source.fetch_consumer_info()
    assert info["error"] == "disconnected"
    assert info["pending_messages"] == 0
    assert info["stream"] == "ORDERS"
    assert info["durable"] == "orders-consumer"


@pytest.mark.asyncio
async def test_fetch_consumer_info_returns_metrics(source) -> None:
    # Setup mock NATS connection.
    delivered = SimpleNamespace(consumer_seq=100, stream_seq=200)
    ack_floor = SimpleNamespace(consumer_seq=95, stream_seq=195)
    info_obj = SimpleNamespace(num_pending=5, delivered=delivered, ack_floor=ack_floor)

    nc = MagicMock()
    nc.is_closed = False
    js = MagicMock()
    js.consumer_info = AsyncMock(return_value=info_obj)
    nc.jetstream = MagicMock(return_value=js)
    source._nc = nc  # type: ignore[attr-defined]

    info = await source.fetch_consumer_info()
    assert info["pending_messages"] == 5
    assert info["delivered_consumer_seq"] == 100
    assert info["delivered_stream_seq"] == 200
    assert info["ack_floor_consumer_seq"] == 95
    assert info["ack_floor_stream_seq"] == 195


@pytest.mark.asyncio
async def test_fetch_consumer_info_handles_jetstream_error(source) -> None:
    nc = MagicMock()
    nc.is_closed = False
    js = MagicMock()
    js.consumer_info = AsyncMock(side_effect=RuntimeError("consumer not found"))
    nc.jetstream = MagicMock(return_value=js)
    source._nc = nc  # type: ignore[attr-defined]

    info = await source.fetch_consumer_info()
    assert "consumer not found" in info["error"]
    assert info["pending_messages"] == 0


def test_register_unregister_nats_source() -> None:
    from src.backend.entrypoints.api.v1.endpoints import admin_nats

    src = MagicMock()
    src.source_id = "nats_js:ORDERS:test-consumer"
    admin_nats.register_nats_source(src)
    assert src.source_id in admin_nats._REGISTRY
    admin_nats.unregister_nats_source(src.source_id)
    assert src.source_id not in admin_nats._REGISTRY


def test_record_consumer_info_no_op_without_prometheus() -> None:
    """No-op если prometheus_client недоступен/ошибка."""
    from src.backend.infrastructure.observability.nats_metrics import (
        record_consumer_info,
    )

    # Без exception на normal данных.
    record_consumer_info(
        {"stream": "X", "durable": "y", "pending_messages": 0}
    )
    record_consumer_info({"stream": "X", "durable": "y", "error": "disconnected"})
