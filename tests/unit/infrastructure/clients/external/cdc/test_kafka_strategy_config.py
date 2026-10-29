"""ADR-0384 — Kafka-стратегия CDC: конфиг брокера, group_id, DLQ, close.

Регрессии волны 16 (кластер X5, дефект 5/8):

* стратегия создавалась без аргументов → ``bootstrap=localhost:9092`` вместо
  настроек брокера;
* общий ``group_id`` → две подписки делили одни и те же партиции;
* poison-offset → бесконечный retry без DLQ;
* исключение в ``consumer.subscribe()`` оставляло consumer незакрытым;
* ``CDCEvent.timestamp`` объявлен как ``str``, а Kafka клал ``datetime`` →
  значение подменялось на ``now()``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.infrastructure.clients.external.cdc.client import CDCClient
from src.backend.infrastructure.clients.external.cdc.events import (
    CDCEvent,
    CDCSubscription,
)
from src.backend.infrastructure.clients.external.cdc.kafka_strategy import (
    _KafkaDebeziumStrategy,
)

# ════════════════════════════════════════════════════════════════════
# Stubs
# ════════════════════════════════════════════════════════════════════


class _FakeTopicPartition:
    """Заглушка ``aiokafka.TopicPartition``."""

    def __init__(self, topic: str, partition: int = 0) -> None:
        self.topic = topic
        self.partition = partition


class _FakeMessage:
    """Заглушка Kafka-сообщения."""

    def __init__(self, value: dict[str, Any], offset: int = 0) -> None:
        self.value = value
        self.offset = offset
        self.headers: list[tuple[str, bytes]] = []


class _StubConsumer:
    """Заглушка ``AIOKafkaConsumer`` — фиксирует параметры и вызовы."""

    instances: list[_StubConsumer] = []

    def __init__(self, *topics: str, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.topics = topics
        self.subscribed: list[str] | None = None
        self.committed: list[Any] = []
        self.stopped = False
        self.started = False
        self.messages: dict[Any, list[_FakeMessage]] = {}
        self.raise_on_subscribe = False
        self._sub: CDCSubscription | None = None
        _StubConsumer.instances.append(self)

    async def start(self) -> None:
        """Старт consumer'а."""
        self.started = True

    def subscribe(self, topics: list[str]) -> None:
        """Подписка на топики (может бросить исключение)."""
        if self.raise_on_subscribe:
            raise RuntimeError("kafka subscribe failed")
        self.subscribed = list(topics)

    async def getmany(
        self, timeout_ms: int | None = None, max_records: int | None = None
    ) -> dict[Any, list[_FakeMessage]]:
        """Вернуть подготовленные сообщения и остановить цикл подписки."""
        if self.messages:
            batch = self.messages
            self.messages = {}
            if self._sub is not None:
                self._sub.active = False
            return batch
        await asyncio.sleep(0.01)
        return {}

    async def commit(self, offsets: Any) -> None:
        """Зафиксировать offset'ы."""
        self.committed.append(offsets)

    async def stop(self) -> None:
        """Остановить consumer."""
        self.stopped = True


class _StubDLQWriter:
    """Заглушка DLQ-writer."""

    def __init__(self) -> None:
        self.envelopes: list[Any] = []

    async def write(self, envelope: Any) -> None:
        """Сохранить envelope."""
        self.envelopes.append(envelope)


@pytest.fixture(autouse=True)
def _reset_stub_consumer() -> None:
    """Сбросить состояние заглушки consumer'а."""
    _StubConsumer.instances = []


@pytest.fixture
def stub_consumer(monkeypatch: pytest.MonkeyPatch) -> type[_StubConsumer]:
    """Подменить ``aiokafka.AIOKafkaConsumer`` заглушкой."""
    import aiokafka

    monkeypatch.setattr(aiokafka, "AIOKafkaConsumer", _StubConsumer)
    return _StubConsumer


# ════════════════════════════════════════════════════════════════════
# 1. Конфиг брокера и group_id
# ════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.asyncio
async def test_kafka_subscription_uses_configured_broker(
    stub_consumer: type[_StubConsumer],
) -> None:
    """Bootstrap-серверы берутся из настроек очереди, а не из localhost."""
    from src.backend.core.config.services.queue import queue_settings

    client = CDCClient(dlq_required=False)
    sub_id = await client.subscribe(
        profile="pg_prod", tables=["orders"], strategy="kafka"
    )

    for _ in range(100):
        if _StubConsumer.instances:
            break
        await asyncio.sleep(0.01)

    assert _StubConsumer.instances, "kafka consumer was not created"
    consumer = _StubConsumer.instances[0]
    expected = f"{queue_settings.host}:{queue_settings.port}"
    assert consumer.kwargs["bootstrap_servers"] == expected
    assert consumer.kwargs["bootstrap_servers"] != "localhost:9092"
    assert client._strategies[sub_id] is not None

    await client.shutdown()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_kafka_group_id_is_unique_per_subscription(
    stub_consumer: type[_StubConsumer],
) -> None:
    """У каждой подписки свой consumer-group (партиции не делятся)."""
    client = CDCClient(dlq_required=False)
    sub_a = await client.subscribe(
        profile="pg_prod", tables=["orders"], strategy="kafka"
    )
    sub_b = await client.subscribe(
        profile="pg_prod", tables=["orders"], strategy="kafka"
    )

    for _ in range(100):
        if len(_StubConsumer.instances) >= 2:
            break
        await asyncio.sleep(0.01)

    assert len(_StubConsumer.instances) == 2
    group_a = _StubConsumer.instances[0].kwargs["group_id"]
    group_b = _StubConsumer.instances[1].kwargs["group_id"]
    assert group_a != group_b
    assert sub_a in group_a
    assert sub_b in group_b

    await client.shutdown()


# ════════════════════════════════════════════════════════════════════
# 2. Poison-offset → DLQ (без бесконечного retry)
# ════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.asyncio
async def test_poison_message_is_sent_to_dlq_and_offset_committed(
    stub_consumer: type[_StubConsumer],
) -> None:
    """Ошибка обработки сообщения → DLQ + commit offset (без бесконечного retry)."""
    poison: list[tuple[dict[str, Any], BaseException]] = []

    async def _poison_handler(
        _sub: CDCSubscription, payload: dict[str, Any], exc: BaseException
    ) -> None:
        poison.append((payload, exc))

    strategy = _KafkaDebeziumStrategy(
        bootstrap_servers="broker:9092",
        group_id="g-test",
        poison_handler=_poison_handler,
    )
    sub = CDCSubscription(profile="pg_prod", tables=["orders"])
    tp = _FakeTopicPartition("pg_prod.orders")
    consumer = _StubConsumer()
    strategy._consumer = consumer
    consumer._sub = sub
    consumer.messages = {
        tp: [_FakeMessage({"op": "c", "after": {"id": 1}}, offset=42)]
    }

    async def _dispatch(_sub: CDCSubscription, _event: CDCEvent) -> None:
        raise RuntimeError("downstream failed")

    await strategy.run(sub, _dispatch)

    assert len(poison) == 1, "poison message was not forwarded to DLQ handler"
    assert poison[0][0]["offset"] == 42
    assert isinstance(poison[0][1], RuntimeError)
    assert consumer.committed, "offset was not committed after DLQ handoff"
    assert consumer.stopped, "consumer was not stopped"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_client_sends_kafka_poison_message_to_dlq(
    stub_consumer: type[_StubConsumer],
) -> None:
    """Клиент пишет poison-сообщение в DLQ и коммитит offset."""
    dlq = _StubDLQWriter()
    client = CDCClient(dlq_required=True)
    client.set_dlq_writer(dlq)

    async def _failing_callback(_event: dict[str, Any]) -> None:
        raise RuntimeError("downstream failed")

    sub_id = await client.subscribe(
        profile="pg_prod",
        tables=["orders"],
        strategy="kafka",
        callback=_failing_callback,
    )
    assert sub_id in client._subscriptions

    for _ in range(100):
        if _StubConsumer.instances:
            break
        await asyncio.sleep(0.01)

    consumer = _StubConsumer.instances[0]
    tp = _FakeTopicPartition("pg_prod.orders")
    consumer.messages = {
        tp: [_FakeMessage({"op": "c", "after": {"id": 1}}, offset=7)]
    }

    for _ in range(100):
        if dlq.envelopes:
            break
        await asyncio.sleep(0.01)

    assert dlq.envelopes, "poison event did not reach DLQ"
    assert dlq.envelopes[0].error_class == "RuntimeError"

    await client.shutdown()


# ════════════════════════════════════════════════════════════════════
# 3. Гарантированное закрытие consumer
# ════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@pytest.mark.asyncio
async def test_consumer_is_stopped_when_subscribe_fails(
    stub_consumer: type[_StubConsumer],
) -> None:
    """Исключение в ``consumer.subscribe()`` не оставляет consumer открытым."""
    strategy = _KafkaDebeziumStrategy(
        bootstrap_servers="broker:9092", group_id="g-test"
    )
    sub = CDCSubscription(profile="pg_prod", tables=["orders"])

    consumer = _StubConsumer()
    consumer.raise_on_subscribe = True
    strategy._consumer = consumer

    async def _dispatch(_sub: CDCSubscription, _event: CDCEvent) -> None:
        return None

    with pytest.raises(RuntimeError, match="kafka subscribe failed"):
        await strategy.run(sub, _dispatch)

    assert consumer.stopped, "consumer was not stopped after subscribe() failure"


# ════════════════════════════════════════════════════════════════════
# 4. Timestamp Kafka-события не подменяется на now()
# ════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_parse_debezium_keeps_source_timestamp() -> None:
    """Timestamp события сохраняется исходным (без подмены на now())."""
    strategy = _KafkaDebeziumStrategy(bootstrap_servers="broker:9092")
    payload = {
        "op": "c",
        "after": {"id": 1},
        "ts_ms": 1700000000000,
    }
    event = strategy._parse_debezium_event(payload, table="orders", profile="pg_prod")
    assert event is not None
    assert event.timestamp == "2023-11-14T22:13:20+00:00"


@pytest.mark.unit
def test_cdc_event_to_dict_serializes_datetime_timestamp() -> None:
    """``CDCEvent.to_dict`` приводит datetime к ISO (значение не теряется)."""
    from datetime import UTC, datetime

    event = CDCEvent(
        operation="INSERT",
        table="orders",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        profile="pg_prod",
    )
    assert event.to_dict()["timestamp"] == "2026-01-01T00:00:00+00:00"
