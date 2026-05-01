"""Wiring W26.3: Kafka → Redis Streams → memory_mq.

Контракт примарного callable:

.. code-block:: python

    async def publish(stream: str, message: dict) -> None: ...

Все три backend'а (Kafka, Redis Streams, in-memory) принимают одинаковую
тройку: имя стрима/топика и payload-словарь. Headers / key опускаем —
они не критичны для durability-fallback'а.

Для Kafka и Redis-Streams используется существующий ``StreamClient``;
для memory — ``InMemoryMessageBroker``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

__all__ = ("MQPublishCallable", "build_mq_fallbacks", "build_mq_primary")

logger = logging.getLogger(__name__)

MQPublishCallable = Callable[[str, dict[str, Any]], Awaitable[None]]


def _stream_client():
    """Lazy-import StreamClient (избегаем циклического импорта при старте)."""
    from src.infrastructure.clients.messaging.stream import get_stream_client

    return get_stream_client()


async def _kafka_publish(stream: str, message: dict[str, Any]) -> None:
    """Primary: Kafka publish через StreamClient."""
    await _stream_client().publish_to_kafka(topic=stream, message=message)


async def _redis_streams_publish(stream: str, message: dict[str, Any]) -> None:
    """Fallback 1: Redis Streams через StreamClient."""
    await _stream_client().publish_to_redis(stream=stream, message=message)


_memory_broker_singleton = None


def _get_memory_broker():
    global _memory_broker_singleton
    if _memory_broker_singleton is None:
        from src.infrastructure.clients.messaging.memory_broker import (
            InMemoryMessageBroker,
        )

        _memory_broker_singleton = InMemoryMessageBroker()
    return _memory_broker_singleton


async def _memory_publish(stream: str, message: dict[str, Any]) -> None:
    """Fallback 2: in-memory fanout broker (last-resort)."""
    broker = _get_memory_broker()
    if not broker._connected:  # noqa: SLF001
        await broker.connect()
    payload = json.dumps(message, default=str).encode()
    await broker.publish(topic=stream, message=payload)


def build_mq_primary() -> MQPublishCallable:
    """Возвращает primary publish-callable (Kafka)."""
    return _kafka_publish


def build_mq_fallbacks() -> dict[str, MQPublishCallable]:
    """Возвращает {chain_id: callable} для fallback-цепочки.

    Идентификаторы соответствуют ``chain`` в base.yml:
    ``["redis_streams", "memory_mq"]``.
    """
    return {"redis_streams": _redis_streams_publish, "memory_mq": _memory_publish}
