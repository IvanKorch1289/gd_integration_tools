"""W23.4 — integration-тесты :class:`MQSource` (Redis-Streams).

Используем встроенный ``TestRedisBroker`` из faststream — in-memory
эмуляция без поднятия настоящего Redis. Перекрываем ``_build_broker``
тем же ``RedisBroker``, обёрнутым в TestRedisBroker через async-context.

Закрывают долг #8: subscriber group-mode требует ``StreamSub``;
позиционный topic + kwargs stream= конфликтовали в faststream 0.6.7.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio

import pytest
from faststream.redis import RedisBroker, StreamSub, TestRedisBroker

from src.backend.core.interfaces.source import SourceEvent
from src.backend.infrastructure.sources.mq import MQSource


def test_make_stream_arg_no_group_returns_topic_string() -> None:
    src = MQSource("orders_in", transport="redis_streams", topic="orders.stream")
    assert src._make_stream_arg() == "orders.stream"


def test_make_stream_arg_group_returns_stream_sub() -> None:
    """Group-mode возвращает StreamSub (а не dict, который ронял faststream)."""
    src = MQSource(
        "orders_in", transport="redis_streams", topic="orders.stream", group="g1"
    )
    arg = src._make_stream_arg()
    assert isinstance(arg, StreamSub)
    assert arg.name == "orders.stream"
    assert arg.group == "g1"
    assert arg.consumer == "orders_in"


@pytest.mark.asyncio
async def test_mq_source_redis_streams_e2e_dispatches_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Полный цикл: TestRedisBroker → MQSource.start → publish → on_event."""
    captured: list[SourceEvent] = []

    async def cb(event: SourceEvent) -> None:
        captured.append(event)

    real_broker = RedisBroker("redis://localhost:6379/0")
    src = MQSource(
        "orders_in",
        transport="redis_streams",
        topic="orders.stream",
        group="gd-orders",
    )

    monkeypatch.setattr(src, "_build_broker", lambda: real_broker)

    async with TestRedisBroker(real_broker):
        await src.start(cb)
        try:
            await real_broker.publish(
                {"order_id": 7, "status": "new"}, stream="orders.stream"
            )
            await asyncio.sleep(0.05)
        finally:
            await src.stop()

    assert len(captured) == 1
    event = captured[0]
    assert event.source_id == "orders_in"
    assert event.payload == {"order_id": 7, "status": "new"}
    assert event.metadata["topic"] == "orders.stream"
    assert event.metadata["transport"] == "redis_streams"


@pytest.mark.asyncio
async def test_mq_source_redis_streams_e2e_no_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без group: stream-подписка по имени, события доставляются."""
    captured: list[SourceEvent] = []

    async def cb(event: SourceEvent) -> None:
        captured.append(event)

    real_broker = RedisBroker("redis://localhost:6379/0")
    src = MQSource("audit_in", transport="redis_streams", topic="audit.stream")
    monkeypatch.setattr(src, "_build_broker", lambda: real_broker)

    async with TestRedisBroker(real_broker):
        await src.start(cb)
        try:
            await real_broker.publish({"e": 1}, stream="audit.stream")
            await asyncio.sleep(0.05)
        finally:
            await src.stop()

    assert len(captured) == 1
    assert captured[0].payload == {"e": 1}
