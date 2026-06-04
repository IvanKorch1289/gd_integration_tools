"""Unit-тесты streaming processors: MessageExpiration, CorrelationId,
TumblingWindow, SlidingWindow, SessionWindow, GroupByKey, SchemaRegistryValidator,
ReplyTo, ExactlyOnce, DurableSubscriber, ChannelPurger, Sampling.

Паттерн: async tests, _ex fixture, моки для broker / storage / clock.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.types.watermark import LatePolicy
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.streaming import (
    ChannelPurgerProcessor,
    CorrelationIdProcessor,
    DurableSubscriberProcessor,
    ExactlyOnceProcessor,
    GroupByKeyProcessor,
    MessageExpirationProcessor,
    ReplyToProcessor,
    SamplingProcessor,
    SchemaRegistryValidator,
    SessionWindowProcessor,
    SlidingWindowProcessor,
    TumblingWindowProcessor,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


class FakeClock:
    """Фиктивные часы для тестов."""

    def __init__(self, start: float = 1000.0) -> None:
        self._t = start

    def time(self) -> float:
        return self._t

    def monotonic(self) -> float:
        return self._t

    def advance(self, delta: float) -> None:
        self._t += delta


# =============================================================================
# MessageExpirationProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_message_expiration_fresh() -> None:
    """Сообщение в пределах TTL → проходит."""
    clock = FakeClock(start=1000.0)
    proc = MessageExpirationProcessor(ttl_seconds=10.0, clock=clock)
    e = _ex(body={}, headers={"x-created-at": "995.0"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.status.value == "pending"
    assert e.error is None


@pytest.mark.asyncio
async def test_message_expiration_expired_fail() -> None:
    """Просроченное сообщение + drop_action=fail → exchange.fail."""
    clock = FakeClock(start=1000.0)
    proc = MessageExpirationProcessor(ttl_seconds=5.0, clock=clock)
    e = _ex(body={}, headers={"x-created-at": "994.0"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.status.value == "failed"
    assert "просрочено" in (e.error or "")


@pytest.mark.asyncio
async def test_message_expiration_expired_skip() -> None:
    """Просроченное + drop_action=skip → свойство _expired, не fail."""
    clock = FakeClock(start=1000.0)
    proc = MessageExpirationProcessor(ttl_seconds=5.0, drop_action="skip", clock=clock)
    e = _ex(body={}, headers={"x-created-at": "994.0"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.properties.get("_expired") is True
    assert e.status.value != "failed"


@pytest.mark.asyncio
async def test_message_expiration_expired_log() -> None:
    """Просроченное + drop_action=log → не fail, не skip."""
    clock = FakeClock(start=1000.0)
    proc = MessageExpirationProcessor(ttl_seconds=5.0, drop_action="log", clock=clock)
    e = _ex(body={}, headers={"x-created-at": "994.0"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.status.value != "failed"
    assert e.properties.get("_expired") is None


@pytest.mark.asyncio
async def test_message_expiration_no_timestamp() -> None:
    """Нет заголовка created_at → проходит."""
    proc = MessageExpirationProcessor(ttl_seconds=5.0)
    e = _ex(body={})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.status.value == "pending"


@pytest.mark.asyncio
async def test_message_expiration_invalid_timestamp() -> None:
    """Невалидный timestamp → проходит."""
    proc = MessageExpirationProcessor(ttl_seconds=5.0)
    e = _ex(body={}, headers={"x-created-at": "not-a-number"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.status.value == "pending"


# =============================================================================
# CorrelationIdProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_correlation_id_sets_new() -> None:
    """Отсутствующий заголовок → генерируется UUID."""
    proc = CorrelationIdProcessor()
    e = _ex(body={})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert "x-correlation-id" in e.in_message.headers
    assert (
        e.properties.get("correlation_id") == e.in_message.headers["x-correlation-id"]
    )


@pytest.mark.asyncio
async def test_correlation_id_preserves_existing() -> None:
    """Существующий заголовок → не перезаписывается."""
    proc = CorrelationIdProcessor()
    e = _ex(body={}, headers={"x-correlation-id": "existing-id"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.in_message.headers["x-correlation-id"] == "existing-id"
    assert "correlation_id" not in e.properties


# =============================================================================
# TumblingWindowProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_tumbling_window_flush_by_size() -> None:
    """При достижении size вызывается sink."""
    sink_calls: list[list[Any]] = []

    def sink(batch: list[Any]) -> None:
        sink_calls.append(batch)

    clock = FakeClock(start=0.0)
    proc = TumblingWindowProcessor(
        sink=sink, size=2, interval_seconds=60.0, clock=clock
    )
    ctx = AsyncMock()

    e1 = _ex(body={"v": 1})
    await proc.process(e1, ctx)
    assert len(sink_calls) == 0

    e2 = _ex(body={"v": 2})
    await proc.process(e2, ctx)
    assert len(sink_calls) == 1
    assert sink_calls[0] == [{"v": 1}, {"v": 2}]


@pytest.mark.asyncio
async def test_tumbling_window_late_event_dropped() -> None:
    """Late event отбрасывается."""
    sink_calls: list[list[Any]] = []

    def sink(batch: list[Any]) -> None:
        sink_calls.append(batch)

    clock = FakeClock(start=100.0)
    proc = TumblingWindowProcessor(
        sink=sink,
        size=10,
        interval_seconds=60.0,
        clock=clock,
        allowed_lateness_seconds=0.0,
        late_policy=LatePolicy.DROP,
    )
    ctx = AsyncMock()

    e = _ex(body={"v": 1})
    e.in_message.watermark = 50.0
    e.in_message.headers["x-event-time"] = "50.0"
    await proc.process(e, ctx)

    assert len(sink_calls) == 0
    assert proc.watermark_state.current >= 50.0


# =============================================================================
# SlidingWindowProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_sliding_window_appends() -> None:
    """Сообщение добавляется в буфер."""
    sink_calls: list[list[Any]] = []

    def sink(batch: list[Any]) -> None:
        sink_calls.append(batch)

    clock = FakeClock(start=0.0)
    proc = SlidingWindowProcessor(
        sink=sink, window_seconds=1.0, step_seconds=0.5, clock=clock
    )
    ctx = AsyncMock()

    e = _ex(body={"v": 1})
    await proc.process(e, ctx)

    # Буфер наполнен, задача эмита запущена
    assert len(proc._buffer) == 1


# =============================================================================
# SessionWindowProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_session_window_appends() -> None:
    """Сообщение добавляется в буфер сессии."""
    sink_calls: list[list[Any]] = []

    def sink(batch: list[Any]) -> None:
        sink_calls.append(batch)

    clock = FakeClock(start=0.0)
    proc = SessionWindowProcessor(sink=sink, gap_seconds=1.0, clock=clock)
    ctx = AsyncMock()

    e = _ex(body={"v": 1})
    await proc.process(e, ctx)

    assert len(proc._buffer) == 1


# =============================================================================
# GroupByKeyProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_group_by_key_groups() -> None:
    """События группируются по ключу."""
    sink_calls: list[dict[Any, list[Any]]] = []

    def sink(groups: dict[Any, list[Any]]) -> None:
        sink_calls.append(groups)

    clock = FakeClock(start=0.0)
    proc = GroupByKeyProcessor(
        sink=sink, key_path="type", window_seconds=0.01, clock=clock
    )
    ctx = AsyncMock()

    e1 = _ex(body={"type": "A", "v": 1})
    e2 = _ex(body={"type": "B", "v": 2})
    e3 = _ex(body={"type": "A", "v": 3})
    await proc.process(e1, ctx)
    await proc.process(e2, ctx)
    await proc.process(e3, ctx)

    # Ждём flush
    await asyncio.sleep(0.05)
    assert len(sink_calls) >= 1
    last = sink_calls[-1]
    assert "A" in last
    assert "B" in last
    assert len(last["A"]) == 2


# =============================================================================
# SchemaRegistryValidator
# =============================================================================


@pytest.mark.asyncio
async def test_schema_validator_missing_schema() -> None:
    """Schema не найдена → exchange.fail."""
    proc = SchemaRegistryValidator(subject="test-schema")
    e = _ex(body={"x": 1})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.status.value == "failed"
    assert "не найдена" in (e.error or "")


@pytest.mark.asyncio
async def test_schema_validator_validation_error() -> None:
    """Тело не соответствует схеме → exchange.fail."""
    schema = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
    }
    proc = SchemaRegistryValidator(subject="num-schema", schema_loader=lambda s: schema)
    e = _ex(body={"y": 1})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.status.value == "failed"
    assert "validation failed" in (e.error or "").lower()


@pytest.mark.asyncio
async def test_schema_validator_cache_hit() -> None:
    """Вторая валидация использует кеш."""
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    loader = MagicMock(return_value=schema)
    proc = SchemaRegistryValidator(subject="cached", schema_loader=loader)

    e1 = _ex(body={"x": 1})
    await proc.process(e1, None)  # type: ignore[arg-type]
    assert e1.status.value != "failed"

    e2 = _ex(body={"x": 2})
    await proc.process(e2, None)  # type: ignore[arg-type]
    assert e2.status.value != "failed"

    loader.assert_called_once()


@pytest.mark.asyncio
async def test_schema_validator_async_loader() -> None:
    """Асинхронный loader корректно awaited."""
    schema = {"type": "object"}

    async def async_loader(subject: str) -> dict[str, Any]:
        return schema

    proc = SchemaRegistryValidator(subject="async", schema_loader=async_loader)
    e = _ex(body={"x": 1})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.status.value != "failed"


# =============================================================================
# ReplyToProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_reply_to_no_header() -> None:
    """Нет reply-to → ничего не делается."""
    broker = AsyncMock()
    proc = ReplyToProcessor(broker=broker)
    e = _ex(body={"result": 42})
    await proc.process(e, None)  # type: ignore[arg-type]

    broker.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_reply_to_success() -> None:
    """Публикует out_message.body в reply-to очередь."""
    broker = AsyncMock()
    proc = ReplyToProcessor(broker=broker)
    e = _ex(body={"in": 1}, headers={"reply-to": "q1", "x-correlation-id": "c1"})
    e.out_message = Message(body={"out": 2})
    await proc.process(e, None)  # type: ignore[arg-type]

    broker.publish.assert_awaited_once_with(
        "q1", {"out": 2}, headers={"x-correlation-id": "c1"}
    )


@pytest.mark.asyncio
async def test_reply_to_publish_error() -> None:
    """Ошибка публикации → exchange.fail."""
    broker = AsyncMock()
    broker.publish.side_effect = RuntimeError("broker down")
    proc = ReplyToProcessor(broker=broker)
    e = _ex(body={"in": 1}, headers={"reply-to": "q1", "x-correlation-id": "c1"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.status.value == "failed"
    assert "broker down" in (e.error or "")


# =============================================================================
# ExactlyOnceProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_exactly_once_missing_id() -> None:
    """Нет message-id → exchange.fail."""
    storage = AsyncMock()
    proc = ExactlyOnceProcessor(storage=storage)
    e = _ex(body={})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.status.value == "failed"
    storage.set_nx.assert_not_awaited()


@pytest.mark.asyncio
async def test_exactly_once_new_message() -> None:
    """Новый message-id → проходит."""
    storage = AsyncMock()
    storage.set_nx.return_value = True
    proc = ExactlyOnceProcessor(storage=storage)
    e = _ex(body={}, headers={"x-message-id": "msg-1"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.status.value != "failed"
    storage.set_nx.assert_awaited_once()


@pytest.mark.asyncio
async def test_exactly_once_duplicate() -> None:
    """Дубль message-id → exchange.fail с _duplicate."""
    storage = AsyncMock()
    storage.set_nx.return_value = False
    proc = ExactlyOnceProcessor(storage=storage)
    e = _ex(body={}, headers={"x-message-id": "msg-1"})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.status.value == "failed"
    assert e.properties.get("_duplicate") is True


# =============================================================================
# DurableSubscriberProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_durable_subscriber_success() -> None:
    """Успешная публикация всем подписчикам."""
    broker = AsyncMock()
    proc = DurableSubscriberProcessor(broker=broker, subscribers=["s1", "s2"])
    e = _ex(body={"event": 1})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert broker.publish.await_count == 2


@pytest.mark.asyncio
async def test_durable_subscriber_partial_failure() -> None:
    """Частичная ошибка → exchange.fail со списком failed."""
    broker = AsyncMock()
    broker.publish.side_effect = [None, RuntimeError("fail")]
    proc = DurableSubscriberProcessor(broker=broker, subscribers=["s1", "s2"])
    e = _ex(body={"event": 1})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.status.value == "failed"
    assert "s2" in (e.error or "")


# =============================================================================
# ChannelPurgerProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_channel_purger_dry_run() -> None:
    """dry_run=True → не удаляет, возвращает info."""
    broker = AsyncMock()
    proc = ChannelPurgerProcessor(broker=broker, channel="dlq", dry_run=True)
    e = _ex(body={})
    e.out_message = Message(body={})
    await proc.process(e, None)  # type: ignore[arg-type]

    broker.purge.assert_not_awaited()
    assert e.out_message.body == {"purged": False, "dry_run": True, "channel": "dlq"}


@pytest.mark.asyncio
async def test_channel_purger_real_purge() -> None:
    """dry_run=False → вызывает broker.purge."""
    broker = AsyncMock()
    broker.purge.return_value = 42
    proc = ChannelPurgerProcessor(broker=broker, channel="dlq", dry_run=False)
    e = _ex(body={})
    e.out_message = Message(body={})
    await proc.process(e, None)  # type: ignore[arg-type]

    broker.purge.assert_awaited_once_with("dlq")
    assert e.out_message.body == {"purged": True, "deleted": 42, "channel": "dlq"}


# =============================================================================
# SamplingProcessor
# =============================================================================


def test_sampling_invalid_probability() -> None:
    with pytest.raises(ValueError, match="probability"):
        SamplingProcessor(probability=1.5)


@pytest.mark.asyncio
async def test_sampling_always_in() -> None:
    """probability=1.0 → всегда проходит."""
    proc = SamplingProcessor(probability=1.0)
    e = _ex(body={})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.properties.get("_sampled_out") is None
    assert e.properties.get("_skip_downstream") is None


@pytest.mark.asyncio
async def test_sampling_always_out() -> None:
    """probability=0.0 → всегда отбрасывается."""
    proc = SamplingProcessor(probability=0.0)
    e = _ex(body={})
    await proc.process(e, None)  # type: ignore[arg-type]

    assert e.properties.get("_sampled_out") is True
    assert e.properties.get("_skip_downstream") is True
