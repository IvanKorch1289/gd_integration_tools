"""Queue push-канал для :class:`InvocationResponse` (W22 этап B).

Push-only backend: публикует JSON-сериализованный response в брокер
(Redis Streams / RabbitMQ / Kafka) через :class:`StreamClient` (FastStream).

Topic/queue и backend-name берутся из ``response.metadata``:

* ``queue_topic`` — имя топика/очереди/stream (обязательное, иначе
  пропускается с warning).
* ``queue_backend`` — ``"redis"`` | ``"rabbit"`` | ``"kafka"`` (default
  ``"redis"``, если совпадает с ``default_backend``).

``fetch`` всегда возвращает ``None`` — push-only канал. Для durable
получения ответа клиент должен подписаться на topic отдельно.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Awaitable, Callable, Literal, Protocol, runtime_checkable

from src.core.interfaces.invocation_reply import (
    InvocationReplyChannel,
    ReplyChannelKind,
)
from src.core.interfaces.invoker import InvocationResponse

__all__ = ("QueueReplyChannel", "QueueBackend", "QueuePublisher")

logger = logging.getLogger("messaging.invocation_replies.queue")

QueueBackend = Literal["redis", "rabbit", "kafka"]


@runtime_checkable
class QueuePublisher(Protocol):
    """Минимальный контракт publisher'а.

    Совместим со :class:`infrastructure.clients.messaging.stream.StreamClient`
    через выбираемый publish-метод. Передаётся в виде callable, чтобы
    канал не зависел от конкретного backend'а напрямую.
    """

    async def __call__(self, topic: str, message: dict[str, Any]) -> None: ...


class QueueReplyChannel(InvocationReplyChannel):
    """Публикует :class:`InvocationResponse` в очередь.

    Args:
        publisher: Опциональный override publisher'а (для тестов или
            кастомных backend'ов). Игнорирует ``response.metadata
            ['queue_backend']`` если задан.
        default_topic: Fallback topic, если ``metadata['queue_topic']`` не
            задан. ``None`` — пропускать доставку.
        default_backend: Используется при lazy-резолве :class:`StreamClient`,
            если ``metadata['queue_backend']`` не задан.
    """

    def __init__(
        self,
        publisher: QueuePublisher | None = None,
        *,
        default_topic: str | None = None,
        default_backend: QueueBackend = "redis",
    ) -> None:
        self._publisher = publisher
        self._default_topic = default_topic
        self._default_backend = default_backend

    @property
    def kind(self) -> ReplyChannelKind:
        return ReplyChannelKind.QUEUE

    async def send(self, response: InvocationResponse) -> None:
        meta = response.metadata or {}
        topic = self._resolve_topic(meta)
        if topic is None:
            logger.warning(
                "QueueReplyChannel: topic не найден в metadata "
                "(invocation_id=%s); доставка пропущена",
                response.invocation_id,
            )
            return

        publisher = self._publisher or self._lazy_publisher(meta)
        if publisher is None:
            logger.warning(
                "QueueReplyChannel: publisher недоступен "
                "(invocation_id=%s, topic=%s); доставка пропущена",
                response.invocation_id,
                topic,
            )
            return

        message = _response_to_dict(response)
        try:
            await publisher(topic, message)
        except Exception:  # noqa: BLE001
            logger.exception(
                "QueueReplyChannel.send failed (invocation_id=%s, topic=%s)",
                response.invocation_id,
                topic,
            )

    async def fetch(self, invocation_id: str) -> InvocationResponse | None:
        return None

    def _resolve_topic(self, meta: dict[str, Any]) -> str | None:
        topic = meta.get("queue_topic")
        if isinstance(topic, str) and topic:
            return topic
        return self._default_topic

    def _lazy_publisher(self, meta: dict[str, Any]) -> QueuePublisher | None:
        """Создаёт publisher через :class:`StreamClient` под выбранный backend.

        Возвращает ``None``, если соответствующий router не инициализирован
        (например, в dev_light без Redis/Rabbit/Kafka).
        """
        backend = self._extract_backend(meta)
        try:
            from src.infrastructure.clients.messaging.stream import get_stream_client

            client = get_stream_client()
        except Exception:  # noqa: BLE001
            return None

        publisher_fn: Callable[..., Awaitable[Any]] | None
        match backend:
            case "redis":
                if client.redis_router is None:
                    return None
                publisher_fn = client.publish_to_redis  # (stream, message, ...)

                async def _redis_publish(topic: str, message: dict[str, Any]) -> None:
                    await publisher_fn(stream=topic, message=message)

                return _redis_publish
            case "rabbit":
                if client.rabbit_router is None:
                    return None
                publisher_fn = client.publish_to_rabbit

                async def _rabbit_publish(topic: str, message: dict[str, Any]) -> None:
                    await publisher_fn(queue=topic, message=message)

                return _rabbit_publish
            case "kafka":
                if client.kafka_router is None:
                    return None
                publisher_fn = client.publish_to_kafka

                async def _kafka_publish(topic: str, message: dict[str, Any]) -> None:
                    await publisher_fn(topic=topic, message=message)

                return _kafka_publish
            case _:
                return None

    def _extract_backend(self, meta: dict[str, Any]) -> QueueBackend:
        raw = meta.get("queue_backend") or self._default_backend
        if raw == "redis" or raw == "rabbit" or raw == "kafka":
            return raw
        return self._default_backend


def _response_to_dict(response: InvocationResponse) -> dict[str, Any]:
    """JSON-friendly dict для FastStream publish."""
    raw = asdict(response)
    raw["status"] = response.status.value
    raw["mode"] = response.mode.value
    return raw
