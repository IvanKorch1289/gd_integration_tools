"""Тесты ``InMemoryMessageBroker`` (Wave 21.3c)."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.infrastructure.clients.messaging.memory_broker import (
    InMemoryMessageBroker,
)


@pytest.mark.asyncio
async def test_publish_subscribe_round_trip():
    broker = InMemoryMessageBroker()
    await broker.connect()
    consumer = await broker.subscribe("topic-a")
    await broker.publish("topic-a", b"hello")
    msg = await asyncio.wait_for(consumer.__anext__(), timeout=1.0)
    assert msg == b"hello"
    await broker.disconnect()


@pytest.mark.asyncio
async def test_fanout_to_multiple_subscribers():
    broker = InMemoryMessageBroker()
    await broker.connect()
    sub1 = await broker.subscribe("t")
    sub2 = await broker.subscribe("t")
    await broker.publish("t", b"hi")
    m1 = await asyncio.wait_for(sub1.__anext__(), timeout=1.0)
    m2 = await asyncio.wait_for(sub2.__anext__(), timeout=1.0)
    assert m1 == b"hi"
    assert m2 == b"hi"
    await broker.disconnect()


@pytest.mark.asyncio
async def test_subscriber_for_other_topic_does_not_receive():
    broker = InMemoryMessageBroker()
    await broker.connect()
    sub = await broker.subscribe("a")
    await broker.publish("b", b"to-b")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.__anext__(), timeout=0.1)
    await broker.disconnect()


@pytest.mark.asyncio
async def test_disconnect_terminates_subscribers():
    broker = InMemoryMessageBroker()
    await broker.connect()
    sub = await broker.subscribe("t")

    async def collect():
        return [m async for m in sub]

    task = asyncio.create_task(collect())
    await broker.publish("t", b"one")
    await asyncio.sleep(0.05)
    await broker.disconnect()
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result == [b"one"]


@pytest.mark.asyncio
async def test_acknowledge_is_no_op():
    broker = InMemoryMessageBroker()
    await broker.connect()
    # Не должно бросать исключений.
    await broker.acknowledge("any-id")
    await broker.disconnect()
