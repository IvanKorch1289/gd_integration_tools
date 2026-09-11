"""Focused tests for ``InMemoryMessageBroker`` (Sprint 24 coverage ratchet).

Цель: поднять покрытие ``src/backend/infrastructure/clients/messaging/memory_broker.py``
с ~31% до ≥70% путём детального покрытия fanout-семантики, lifecycle и
edge-кейсов (disconnect → EOF, QueueFull, group ignore, headers ignore).

Контракт API (см. memory_broker.py):
- ``__init__(*, max_queue_size=1024)`` — атрибут ``_max``.
- ``connect()`` / ``disconnect()`` — флаг ``_connected``.
- ``publish(topic, message, headers=None)`` — fanout по всем queues топика.
- ``subscribe(topic, group=None)`` — async-функция, возвращает ``AsyncIterator[bytes]``;
  ``group`` ignored.
- ``acknowledge(message_id)`` — no-op.
- ``disconnect()`` шлёт ``_EOF`` всем consumer-queues (cleanup registry).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from src.backend.infrastructure.clients.messaging.memory_broker import (
    InMemoryMessageBroker,
)


class TestInMemoryMessageBrokerInit:
    """``__init__`` + sync-only smoke-тесты."""

    def test_init_default(self) -> None:
        """Default ``max_queue_size=1024`` → ``_max == 1024``."""
        broker = InMemoryMessageBroker()
        assert broker._max == 1024
        assert broker._connected is False
        assert isinstance(broker._consumers, dict)
        assert len(broker._consumers) == 0

    def test_init_custom_queue_size(self) -> None:
        """Custom ``max_queue_size=512`` → ``_max == 512``."""
        broker = InMemoryMessageBroker(max_queue_size=512)
        assert broker._max == 512

    def test_init_keyword_only(self) -> None:
        """``max_queue_size`` — keyword-only (после звёздочки)."""
        with pytest.raises(TypeError):
            InMemoryMessageBroker(256)  # type: ignore[misc]

    def test_consumers_defaultdict(self) -> None:
        """``_consumers`` — defaultdict с set-значениями."""
        broker = InMemoryMessageBroker()
        # Доступ к несуществующему ключу создаёт пустой set.
        assert broker._consumers["missing-topic"] == set()


class TestConnectLifecycle:
    """``connect()`` / ``disconnect()`` — базовый lifecycle."""

    async def test_connect_sets_connected_true(self) -> None:
        """``connect()`` переключает ``_connected`` → True."""
        broker = InMemoryMessageBroker()
        await broker.connect()
        assert broker._connected is True

    async def test_disconnect_sets_connected_false(self) -> None:
        """``disconnect()`` переключает ``_connected`` → False."""
        broker = InMemoryMessageBroker()
        await broker.connect()
        await broker.disconnect()
        assert broker._connected is False


class TestPublishFanout:
    """``publish()`` — fanout-семантика по подписчикам одного топика."""

    async def test_publish_without_subscribers_no_error(self) -> None:
        """``publish()`` без подписчиков — no-op, не падает."""
        broker = InMemoryMessageBroker()
        await broker.connect()
        # Не должно бросить исключение.
        await broker.publish(topic="empty", message=b"orphan")

    async def test_publish_to_single_subscriber(self) -> None:
        """``publish()`` → один подписчик получает сообщение."""
        broker = InMemoryMessageBroker()
        await broker.connect()

        received: list[bytes] = []

        async def _consume() -> None:
            it: AsyncIterator[bytes] = await broker.subscribe("t1")
            async for msg in it:
                received.append(msg)
                break  # consume only first message

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)  # даём подписчику зарегистрироваться
        await broker.publish("t1", b"hello")

        await asyncio.wait_for(task, timeout=1.0)
        assert received == [b"hello"]

    async def test_publish_fanout_multiple_subscribers(self) -> None:
        """``publish()`` → все подписчики топика получают копию (fanout)."""
        broker = InMemoryMessageBroker()
        await broker.connect()

        received_a: list[bytes] = []
        received_b: list[bytes] = []

        async def _consume_a() -> None:
            it = await broker.subscribe("broadcast")
            async for msg in it:
                received_a.append(msg)
                break

        async def _consume_b() -> None:
            it = await broker.subscribe("broadcast")
            async for msg in it:
                received_b.append(msg)
                break

        task_a = asyncio.create_task(_consume_a())
        task_b = asyncio.create_task(_consume_b())
        await asyncio.sleep(0.01)

        await broker.publish("broadcast", b"shared")

        await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=1.0)
        assert received_a == [b"shared"]
        assert received_b == [b"shared"]


class TestSubscribe:
    """``subscribe()`` — async-iterator, group ignored."""

    async def test_subscribe_returns_async_iterator(self) -> None:
        """``subscribe()`` возвращает ``AsyncIterator[bytes]``."""
        broker = InMemoryMessageBroker()
        await broker.connect()

        it: AsyncIterator[bytes] = await broker.subscribe("t")
        assert hasattr(it, "__aiter__")
        assert hasattr(it, "__anext__")

        await broker.disconnect()  # cleanup → EOF → завершение итератора

    async def test_subscribe_group_ignored(self) -> None:
        """Параметр ``group`` игнорируется (нет consumer-group семантики)."""
        broker = InMemoryMessageBroker()
        await broker.connect()

        received: list[bytes] = []

        async def _consume() -> None:
            # Передаём group — должно игнорироваться.
            it = await broker.subscribe("grouped", group="my-group")
            async for msg in it:
                received.append(msg)
                break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)
        await broker.publish("grouped", b"payload")
        await asyncio.wait_for(task, timeout=1.0)
        assert received == [b"payload"]


class TestAcknowledge:
    """``acknowledge()`` — no-op, не падает."""

    async def test_acknowledge_no_op(self) -> None:
        """``acknowledge()`` принимает любой message_id без побочных эффектов."""
        broker = InMemoryMessageBroker()
        await broker.connect()
        # Не должно бросить исключение.
        await broker.acknowledge("any-id-123")
        await broker.acknowledge("")
        await broker.acknowledge("unicode-тест-🔧")

    async def test_acknowledge_before_connect(self) -> None:
        """``acknowledge()`` работает даже без ``connect()`` (no-op)."""
        broker = InMemoryMessageBroker()
        # Не вызывали connect().
        await broker.acknowledge("id")


class TestPublishQueueFull:
    """``publish()`` с заполненной очередью — drop on full (graceful)."""

    async def test_publish_to_full_queue_drops(self) -> None:
        """``QueueFull`` → drop, не raise."""
        broker = InMemoryMessageBroker(max_queue_size=1)
        await broker.connect()

        # Создаём подписчика, который НЕ consume'ит → очередь заполнится.
        async def _slow_consumer() -> None:
            it = await broker.subscribe("backpressure")
            async for _ in it:
                # Блокирующий consume → очередь заполнится на 2-м publish.
                await asyncio.Event().wait()  # never set

        task = asyncio.create_task(_slow_consumer())
        await asyncio.sleep(0.01)

        # Первый publish проходит (queue size 1).
        await broker.publish("backpressure", b"msg1")

        # Второй publish должен drop'нуться (QueueFull → silently dropped).
        # Если бы НЕ было try/except — был бы asyncio.QueueFull.
        await broker.publish("backpressure", b"msg2")
        await broker.publish("backpressure", b"msg3")

        # Cleanup.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await broker.disconnect()


class TestPublishHeaders:
    """``publish()`` с headers — параметр принимается, но игнорируется."""

    async def test_publish_with_headers(self) -> None:
        """``headers`` kw-arg принимается, но не используется in-memory broker."""
        broker = InMemoryMessageBroker()
        await broker.connect()

        received: list[bytes] = []

        async def _consume() -> None:
            it = await broker.subscribe("hdr-topic")
            async for msg in it:
                received.append(msg)
                break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.01)
        # Передаём headers — не должно упасть.
        await broker.publish("hdr-topic", b"data", headers={"x-trace-id": "abc123"})

        await asyncio.wait_for(task, timeout=1.0)
        assert received == [b"data"]
