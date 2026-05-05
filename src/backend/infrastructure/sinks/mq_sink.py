"""MqSink — публикация в Kafka / RabbitMQ / Redis-Streams (Wave 3.1).

Реализован через FastStream-publishers (broker уже в стеке проекта,
см. ``infrastructure/messaging/``). Lazy-импорт конкретного broker'а
по полю :attr:`broker`.

Wave 3 поднимает FastStream до ``>=0.6.7`` (см. pyproject.toml) —
breaking changes в 0.6 затрагивают `RabbitRouter.max_consumers`
default; здесь используется только `Broker.publish(...)`, который
стабилен между 0.5/0.6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.backend.utilities.codecs.json import dumps_str

__all__ = ("MqSink",)


BrokerKind = Literal["kafka", "rabbit", "redis", "nats"]


@dataclass(slots=True)
class MqSink(Sink):
    """Publisher-sink для Kafka/Rabbit/Redis-Streams/NATS.

    Args:
        sink_id: Уникальный идентификатор.
        broker: Имя broker'а (``"kafka"``, ``"rabbit"``, ``"redis"``,
            ``"nats"``).
        url: Broker URL (``"localhost:9092"`` для Kafka,
            ``"amqp://..."`` для Rabbit, ``"redis://..."`` для Redis,
            ``"nats://..."`` для NATS).
        topic: Topic / exchange / stream / subject — куда публикуем.
        extra: Доп.параметры для конкретного broker'а (routing_key,
            partition, headers).
    """

    sink_id: str
    broker: BrokerKind
    url: str
    topic: str
    extra: dict[str, Any] = field(default_factory=dict)
    kind: SinkKind = field(default=SinkKind.MQ, init=False)

    async def send(self, payload: Any) -> SinkResult:
        """Публикует ``payload`` через FastStream-broker."""
        broker = await self._build_broker()
        if broker is None:
            return SinkResult(
                ok=False, details={"error": f"faststream/{self.broker} not installed"}
            )

        body = payload if isinstance(payload, (bytes, str)) else dumps_str(payload)

        try:
            await broker.connect()
            try:
                await broker.publish(body, self.topic, **self.extra)
            finally:
                await broker.close()
        except Exception as exc:  # noqa: BLE001
            return SinkResult(
                ok=False, details={"error": str(exc) or exc.__class__.__name__}
            )

        return SinkResult(ok=True, details={"broker": self.broker, "topic": self.topic})

    async def health(self) -> bool:
        """Health: connect/close без публикации."""
        broker = await self._build_broker()
        if broker is None:
            return False
        try:
            await broker.connect()
            await broker.close()
        except Exception:  # noqa: BLE001
            return False
        return True

    async def _build_broker(self) -> Any:
        """Lazy-конструирование FastStream-broker по типу."""
        try:
            if self.broker == "kafka":
                from faststream.kafka import KafkaBroker

                return KafkaBroker(self.url)
            if self.broker == "rabbit":
                from faststream.rabbit import RabbitBroker

                return RabbitBroker(self.url)
            if self.broker == "redis":
                from faststream.redis import RedisBroker

                return RedisBroker(self.url)
            if self.broker == "nats":
                from faststream.nats import NatsBroker

                return NatsBroker(self.url)
        except ImportError:
            return None
        return None
