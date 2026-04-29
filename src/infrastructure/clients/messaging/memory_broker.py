"""``InMemoryMessageBroker`` — fallback на ``asyncio.Queue`` (Wave 21.3c).

Реализация :class:`src.core.interfaces.MessageBroker`. Используется в
dev_light, где Kafka/RabbitMQ/Redis Streams недоступны. Подходит также
для unit/integration-тестов, чтобы избегать testcontainers.

Семантика:
- ``publish(topic, msg)`` — non-blocking, рассылает каждому подписчику
  топика (fanout).
- ``subscribe(topic, group=None)`` — возвращает async-итератор; ``group``
  игнорируется (несколько subscribers одного топика получают одинаковую
  копию каждого сообщения).
- ``acknowledge`` — no-op (ack/nack не моделируется в in-memory).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import AsyncIterator

from src.core.interfaces import MessageBroker

__all__ = ("InMemoryMessageBroker",)


_EOF = b""


class InMemoryMessageBroker(MessageBroker):
    """Fanout-broker на ``asyncio.Queue`` (in-process, не сериализуется)."""

    def __init__(self, *, max_queue_size: int = 1024) -> None:
        self._max = max_queue_size
        self._consumers: dict[str, set[asyncio.Queue[bytes]]] = defaultdict(set)
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        for queues in self._consumers.values():
            for q in queues:
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(_EOF)
        self._consumers.clear()

    async def publish(
        self,
        topic: str,
        message: bytes,
        headers: dict[str, str] | None = None,
    ) -> None:
        del headers  # in-memory broker не использует headers
        for q in list(self._consumers.get(topic, ())):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                # Drop on full — для dev-сценария это приемлемо.
                pass

    async def subscribe(
        self, topic: str, group: str | None = None
    ) -> AsyncIterator[bytes]:
        del group
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=self._max)
        self._consumers[topic].add(q)
        return _drain(q, self._consumers[topic])

    async def acknowledge(self, message_id: str) -> None:
        del message_id  # in-memory без durability — ack не нужен


async def _drain(
    q: asyncio.Queue[bytes], registry: set[asyncio.Queue[bytes]]
) -> AsyncIterator[bytes]:
    """Читает из ``q`` до EOF-маркера; снимает себя из ``registry`` по выходу."""
    try:
        while True:
            msg = await q.get()
            if msg == _EOF:
                break
            yield msg
    finally:
        registry.discard(q)
