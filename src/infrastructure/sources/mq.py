"""W23.4 — :class:`MQSource` на базе FastStream.

Один класс — четыре transport: ``redis_streams`` (dev_light-friendly),
``kafka``, ``rabbitmq``, ``nats``. Все backend'ы идут через единый API
``faststream.{redis,kafka,rabbit,nats}.{Broker, ...}`` — это та же
абстракция, что уже используется в ``infrastructure/clients/messaging``.
Прямые ``aiokafka``/``aio-pika``/``nats-py`` остаются только как
транзитивные зависимости faststream.

Контракт on_event: сообщение → ``SourceEvent``; payload — декодированный
JSON либо raw bytes; metadata — топик/offset/headers (зависит от broker).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from src.core.interfaces.source import EventCallback, SourceEvent, SourceKind

if TYPE_CHECKING:
    pass

__all__ = ("MQSource", "MQTransport")

logger = logging.getLogger("infrastructure.sources.mq")

MQTransport = Literal["redis_streams", "kafka", "rabbitmq", "nats"]


class MQSource:
    """Универсальный MQ-источник поверх FastStream.

    Args:
        source_id: Уникальный id.
        transport: ``redis_streams`` / ``kafka`` / ``rabbitmq`` / ``nats``.
        topic: Топик / stream / queue / subject.
        group: Consumer-group (Kafka group_id, Redis-Streams group,
            RabbitMQ queue без group использует exclusive consumer; для
            NATS — queue group).
        connect_url: URL подключения (зависит от transport).
        decode_json: Пытаться ли декодировать payload как JSON.
    """

    kind: SourceKind = SourceKind.MQ

    def __init__(
        self,
        source_id: str,
        *,
        transport: MQTransport,
        topic: str,
        group: str | None = None,
        connect_url: str | None = None,
        decode_json: bool = True,
    ) -> None:
        self.source_id = source_id
        self._transport = transport
        self._topic = topic
        self._group = group
        self._url = connect_url
        self._decode = decode_json
        self._broker: Any = None
        self._lock = asyncio.Lock()

    async def start(self, on_event: EventCallback) -> None:
        async with self._lock:
            if self._broker is not None:
                raise RuntimeError(f"MQSource(id={self.source_id!r}) уже запущен")
            self._broker = self._build_broker()

            async def _handler(msg: Any) -> None:
                await self._on_message(on_event, msg)

            self._register_subscriber(_handler)
            await self._broker.start()
        logger.info(
            "MQSource started: id=%s transport=%s topic=%s",
            self.source_id,
            self._transport,
            self._topic,
        )

    async def stop(self) -> None:
        async with self._lock:
            if self._broker is None:
                return
            try:
                await self._broker.close()
            finally:
                self._broker = None
        logger.info("MQSource stopped: id=%s", self.source_id)

    async def health(self) -> bool:
        return self._broker is not None

    # ─────────────────── broker selection ───────────────────

    def _build_broker(self) -> Any:
        match self._transport:
            case "redis_streams":
                from faststream.redis import RedisBroker

                return RedisBroker(self._url or "redis://localhost:6379/0")
            case "kafka":
                from faststream.kafka import KafkaBroker

                return KafkaBroker(self._url or "localhost:9092")
            case "rabbitmq":
                from faststream.rabbit import RabbitBroker

                return RabbitBroker(self._url or "amqp://guest:guest@localhost/")
            case "nats":
                from faststream.nats import NatsBroker

                return NatsBroker(self._url or "nats://localhost:4222")
            case _:
                raise ValueError(f"Unknown MQ transport: {self._transport!r}")

    def _register_subscriber(self, handler: Any) -> None:
        """Регистрирует subscriber на ``self._broker`` под каждый transport.

        Подписка зависит от API конкретного брокера:
        Redis — kwargs ``stream=`` (str | StreamSub); Kafka — позиционный
        topic + ``group_id``; Rabbit — позиционный queue; NATS —
        позиционный subject + ``queue=`` для group.
        """
        match self._transport:
            case "redis_streams":
                stream_arg = self._make_stream_arg()
                self._broker.subscriber(stream=stream_arg)(handler)
            case "kafka":
                if self._group:
                    self._broker.subscriber(self._topic, group_id=self._group)(handler)
                else:
                    self._broker.subscriber(self._topic)(handler)
            case "rabbitmq":
                self._broker.subscriber(self._topic)(handler)
            case "nats":
                if self._group:
                    self._broker.subscriber(self._topic, queue=self._group)(handler)
                else:
                    self._broker.subscriber(self._topic)(handler)
            case _:
                raise ValueError(f"Unknown MQ transport: {self._transport!r}")

    def _make_stream_arg(self) -> Any:
        """Stream-аргумент Redis-subscriber: str (без group) или StreamSub."""
        if not self._group:
            return self._topic
        # faststream 0.6+ требует StreamSub для group-consumer'ов;
        # dict-вариант роняет factory с AttributeError.
        from faststream.redis import StreamSub

        return StreamSub(
            stream=self._topic, group=self._group, consumer=str(self.source_id)
        )

    # ─────────────────── on_message ───────────────────

    def _decode_payload(self, raw: Any) -> Any:
        if isinstance(raw, (dict, list)):
            return raw  # faststream уже декодировал
        if isinstance(raw, str):
            data = raw.encode()
        elif isinstance(raw, (bytes, bytearray)):
            data = bytes(raw)
        else:
            return raw
        if not self._decode:
            return data
        try:
            import orjson

            return orjson.loads(data)
        except Exception:
            return data.decode(errors="replace")

    async def _on_message(self, on_event: EventCallback, msg: Any) -> None:
        # Faststream передаёт декодированный body как первый аргумент;
        # мета-информация — в msg.raw_message и msg.headers (если доступно).
        try:
            payload = self._decode_payload(msg)
            metadata: dict[str, Any] = {
                "topic": self._topic,
                "transport": self._transport,
            }
            event = SourceEvent(
                source_id=self.source_id,
                kind=self.kind,
                payload=payload,
                event_time=datetime.now(UTC),
                metadata=metadata,
            )
            await on_event(event)
        except Exception as exc:
            logger.error("MQSource on_event failed (%s): %s", self._transport, exc)
