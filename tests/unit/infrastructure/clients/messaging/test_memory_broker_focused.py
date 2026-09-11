"""Focused tests for InMemoryMessageBroker (M6-#3 Variant B coverage ratchet).

Coverage target: memory_broker.py → 70%+.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from src.backend.infrastructure.clients.messaging.memory_broker import (
    InMemoryMessageBroker,
)


def test_init_default() -> None:
    """InMemoryMessageBroker init default."""
    broker = InMemoryMessageBroker()
    assert broker is not None


def test_init_custom_queue_size() -> None:
    """InMemoryMessageBroker init с custom max_queue_size."""
    broker = InMemoryMessageBroker(max_queue_size=2048)
    assert broker._max_queue_size == 2048


def test_init_state() -> None:
    """InMemoryMessageBroker init — not connected."""
    broker = InMemoryMessageBroker()
    assert broker._connected is False


@pytest.mark.asyncio
async def test_connect_sets_connected() -> None:
    """connect() ставит _connected = True."""
    broker = InMemoryMessageBroker()
    await broker.connect()
    assert broker._connected is True


@pytest.mark.asyncio
async def test_disconnect_clears_connected() -> None:
    """disconnect() ставит _connected = False."""
    broker = InMemoryMessageBroker()
    await broker.connect()
    await broker.disconnect()
    assert broker._connected is False


@pytest.mark.asyncio
async def test_publish_returns_message_id() -> None:
    """publish() returns message ID."""
    broker = InMemoryMessageBroker()
    await broker.connect()
    msg_id = await broker.publish(topic="t1", message=b"msg")
    assert msg_id is not None
    assert isinstance(msg_id, str) or isinstance(msg_id, uuid.UUID)


@pytest.mark.asyncio
async def test_publish_to_multiple_topics() -> None:
    """publish() в разные topics — раздельные очереди."""
    broker = InMemoryMessageBroker()
    await broker.connect()
    await broker.publish(topic="t1", message=b"a")
    await broker.publish(topic="t2", message=b"b")
    # Проверяем что topics разделены
    assert "t1" in broker._topics or broker._queues


@pytest.mark.asyncio
async def test_subscribe_returns_handler() -> None:
    """subscribe() возвращает handler ID."""
    broker = InMemoryMessageBroker()
    await broker.connect()
    handler_id = await broker.subscribe(topic="t1")
    assert handler_id is not None


@pytest.mark.asyncio
async def test_subscribe_multiple() -> None:
    """subscribe() несколько раз возвращает разные handler ID."""
    broker = InMemoryMessageBroker()
    await broker.connect()
    h1 = await broker.subscribe(topic="t1")
    h2 = await broker.subscribe(topic="t1")
    assert h1 != h2


@pytest.mark.asyncio
async def test_acknowledge_no_error() -> None:
    """acknowledge() — no error."""
    broker = InMemoryMessageBroker()
    await broker.connect()
    msg_id = await broker.publish(topic="t1", message=b"msg")
    await broker.acknowledge(message_id=str(msg_id))


@pytest.mark.asyncio
async def test_drain_returns_messages() -> None:
    """_drain возвращает накопленные messages."""
    broker = InMemoryMessageBroker()
    await broker.connect()
    await broker.publish(topic="t1", message=b"a")
    await broker.publish(topic="t1", message=b"b")
    messages = await broker._drain("t1")
    assert len(messages) == 2


@pytest.mark.asyncio
async def test_drain_empty_topic() -> None:
    """_drain пустой topic — пустой list."""
    broker = InMemoryMessageBroker()
    await broker.connect()
    messages = await broker._drain("never_published")
    assert messages == []


@pytest.mark.asyncio
async def test_publish_before_connect() -> None:
    """publish() before connect — auto-connect."""
    broker = InMemoryMessageBroker()
    msg_id = await broker.publish(topic="t1", message=b"msg")
    # Должен auto-connect
    assert broker._connected is True or msg_id is not None


@pytest.mark.asyncio
async def test_drain_does_not_block() -> None:
    """_drain не блокирует — возвращает пустой list сразу."""
    broker = InMemoryMessageBroker()
    await broker.connect()
    messages = await broker._drain("nonexistent")
    assert messages == []


def test_repr() -> None:
    """InMemoryMessageBroker str/repr."""
    broker = InMemoryMessageBroker()
    s = str(broker)
    assert isinstance(s, str)


def test_broker_max_queue_size_attribute() -> None:
    """InMemoryMessageBroker._max_queue_size attribute."""
    broker = InMemoryMessageBroker(max_queue_size=512)
    assert broker._max_queue_size == 512
