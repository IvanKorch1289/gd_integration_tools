"""Event Message EIP processor (Sprint 56 W1).

Apache Camel Event Message:
https://camel.apache.org/components/latest/eips/event-message.html

Event Message — паттерн для асинхронной доставки сообщений между
producer/consumer через ``Event Channel`` (в нашем случае — message
broker: Kafka / RabbitMQ / NATS / Redis Streams). Сообщение обогащается
metadata headers: ``event_type``, ``event_id``, ``event_timestamp``,
``event_version`` — стандарт CloudEvents-like envelope.

Использование::

    from src.backend.dsl.engine.processors.eip.event_message import (
        EventMessageProcessor,
    )

    # Producer side — обогащает и публикует
    .process(EventMessageProcessor(
        event_type="customer.created",
        event_version="1.0",
        topic="customer-events",
        producer=kafka_producer,  # callable: (topic, body, headers) -> None
    ))

    # В header producer может не принимать — только обогащение
    .process(EventMessageProcessor(
        event_type="order.shipped",
        event_version="2.1",
        event_id="evt-123",  # explicit, иначе UUID4
    ))

Thread-safe: state minimal; ``id_generator`` может быть передан для
custom ID strategy (e.g., ULID, snowflake). Lock для counters.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("EventMessageEnvelope", "EventMessageProcessor")

_log = get_logger(__name__)


# Header constants — стандартные имена (CloudEvents-like).
HEADER_EVENT_ID = "event_id"
HEADER_EVENT_TYPE = "event_type"
HEADER_EVENT_VERSION = "event_version"
HEADER_EVENT_TIMESTAMP = "event_timestamp"  # ISO 8601 / epoch_ms
HEADER_EVENT_SOURCE = "event_source"  # producer / service name
HEADER_EVENT_TOPIC = "event_topic"  # канал доставки

# Optional: producer callable — (topic, body, headers) → None (sync) or Awaitable.
EventProducer = Callable[[str, Any, dict[str, Any]], Any | Awaitable[Any]]


def _default_id_generator() -> str:
    """Default: UUID4."""
    return str(uuid.uuid4())


def _default_timestamp() -> str:
    """Default: ISO 8601 UTC (millisecond precision)."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + (
        f".{int((time.time() % 1) * 1000):03d}Z"
    )


class EventMessageEnvelope:
    """Immutable CloudEvents-like envelope.

    Useful для testing и explicit creation без exchange headers.
    """

    __slots__ = (
        "event_id",
        "event_type",
        "event_version",
        "event_timestamp",
        "event_source",
        "topic",
        "body",
    )

    def __init__(
        self,
        *,
        event_id: str,
        event_type: str,
        event_version: str,
        event_timestamp: str,
        event_source: str | None,
        topic: str | None,
        body: Any,
    ) -> None:
        self.event_id = event_id
        self.event_type = event_type
        self.event_version = event_version
        self.event_timestamp = event_timestamp
        self.event_source = event_source
        self.topic = topic
        self.body = body

    def to_headers(self) -> dict[str, str]:
        h: dict[str, str] = {
            HEADER_EVENT_ID: self.event_id,
            HEADER_EVENT_TYPE: self.event_type,
            HEADER_EVENT_VERSION: self.event_version,
            HEADER_EVENT_TIMESTAMP: self.event_timestamp,
        }
        if self.event_source is not None:
            h[HEADER_EVENT_SOURCE] = self.event_source
        if self.topic is not None:
            h[HEADER_EVENT_TOPIC] = self.topic
        return h

    def __repr__(self) -> str:
        return (
            f"EventMessageEnvelope(id={self.event_id!r}, "
            f"type={self.event_type!r}, v={self.event_version!r})"
        )


class EventMessageProcessor(BaseProcessor):
    """Обогащает message event-metadata + опционально публикует в канал.

    Args:
        event_type: семантический тип события (e.g., ``order.created``).
        event_version: версия схемы события (e.g., ``1.0``).
        event_source: producer/service identifier (e.g., ``billing-svc``).
            Если ``None`` — берётся из header ``event_source`` или default.
        topic: имя канала (Kafka topic / RabbitMQ exchange / NATS subject).
            Если ``None`` — только обогащение, без публикации.
        producer: callable для публикации. Если ``None`` — обогащение только.
        id_generator: callable → str (default UUID4). Можно заменить на ULID/snowflake.
        timestamp_fn: callable → str (default ISO 8601 UTC). Можно подменить
            на epoch_ms или RFC 3339 nano.
        name: имя процессора.

    Side effects (если producer задан): публикация в external channel.
    """

    # Классифицируется как SIDE_EFFECTING при наличии producer (публикация в Kafka/RabbitMQ/NATS).
    # Если producer=None — остаётся PURE (только header enrichment).
    side_effect: ClassVar[SideEffectKind] = (
        SideEffectKind.PURE
    )  # default; producer=None → PURE

    def __init__(  # noqa: PLR0913
        self,
        *,
        event_type: str,
        event_version: str = "1.0",
        event_source: str | None = None,
        topic: str | None = None,
        producer: EventProducer | None = None,
        id_generator: Callable[[], str] | None = None,
        timestamp_fn: Callable[[], str] | None = None,
        name: str | None = None,
    ) -> None:
        if not event_type:
            raise ValueError("EventMessageProcessor: event_type is required")
        super().__init__(name=name or "event_message")
        self._event_type = event_type
        self._event_version = event_version
        self._event_source = event_source
        self._topic = topic
        self._producer = producer
        self._id_generator = id_generator or _default_id_generator
        self._timestamp_fn = timestamp_fn or _default_timestamp
        self._lock = threading.Lock()
        self._publish_count = 0
        self._enrich_count = 0

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обогащает exchange CloudEvents-совместимыми заголовками и опционально публикует.

        Резолвит event_id, event_timestamp, event_source из заголовков или
        генерирует defaults. Формирует :class:`EventMessageEnvelope`,
        устанавливает CloudEvents-заголовки (id, type, version, timestamp,
        source, topic). Если задан ``producer`` и ``topic`` — публикует
        тело в внешний канал.

        Args:
            exchange: Текущий exchange; envelope — в свойстве ``event.envelope``.
            context: Контекст выполнения маршрута.
        """
        # Resolve event_id: explicit header > generated.
        existing_id = exchange.in_message.get_header(HEADER_EVENT_ID)
        event_id = str(existing_id) if existing_id else self._id_generator()

        # Resolve event_timestamp: explicit header > generated.
        existing_ts = exchange.in_message.get_header(HEADER_EVENT_TIMESTAMP)
        event_ts = str(existing_ts) if existing_ts else self._timestamp_fn()

        # Resolve event_source.
        existing_source = exchange.in_message.get_header(HEADER_EVENT_SOURCE)
        event_source = str(existing_source) if existing_source else self._event_source

        # Set headers on in_message.
        exchange.in_message.set_header(HEADER_EVENT_ID, event_id)
        exchange.in_message.set_header(HEADER_EVENT_TYPE, self._event_type)
        exchange.in_message.set_header(HEADER_EVENT_VERSION, self._event_version)
        exchange.in_message.set_header(HEADER_EVENT_TIMESTAMP, event_ts)
        if event_source is not None:
            exchange.in_message.set_header(HEADER_EVENT_SOURCE, event_source)
        if self._topic is not None:
            exchange.in_message.set_header(HEADER_EVENT_TOPIC, self._topic)

        envelope = EventMessageEnvelope(
            event_id=event_id,
            event_type=self._event_type,
            event_version=self._event_version,
            event_timestamp=event_ts,
            event_source=event_source,
            topic=self._topic,
            body=exchange.in_message.body,
        )
        exchange.set_property("event.envelope", envelope)

        with self._lock:
            self._enrich_count += 1

        _log.debug(
            "EventMessage: enriched id=%s type=%s v=%s",
            event_id,
            self._event_type,
            self._event_version,
        )

        if self._producer is None or self._topic is None:
            return

        # Publish to external channel.
        try:
            result = self._producer(
                self._topic, exchange.in_message.body, envelope.to_headers()
            )
            if _isawaitable(result):
                await result
        except Exception:
            with self._lock:
                self._publish_count += 1
            raise

        with self._lock:
            self._publish_count += 1
        _log.debug("EventMessage: published to %s", self._topic)

    def stats(self) -> dict[str, int]:
        """Snapshot of enrichment/publish counters."""
        with self._lock:
            return {"enrichments": self._enrich_count, "publishes": self._publish_count}

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "event_message",
            "event_type": self._event_type,
            "event_version": self._event_version,
            "event_source": self._event_source,
            "topic": self._topic,
        }


def _isawaitable(value: Any) -> bool:
    import inspect

    return inspect.isawaitable(value)
