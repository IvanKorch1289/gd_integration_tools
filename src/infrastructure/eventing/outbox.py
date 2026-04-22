"""Transactional Outbox Pattern (ADR-011).

Dual-write problem: commit to DB + publish to broker не атомарны. При
падении после commit и до publish (или наоборот) возникают
рассогласования — критично для банковских транзакций.

Решение: в той же транзакции, что меняет бизнес-сущность, записывается
строка в таблицу ``outbox_events``. Отдельный background worker
периодически (или через LISTEN/NOTIFY) читает необработанные события,
публикует в broker и помечает как published.

Alembic-миграция таблицы ``outbox_events`` — в follow-up.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

__all__ = ("OutboxEvent", "OutboxPublisher")

logger = logging.getLogger("eventing.outbox")


@dataclass(slots=True)
class OutboxEvent:
    """Строка таблицы ``outbox_events``.

    Записывается в той же транзакции, что и бизнес-сущность.
    """

    id: UUID = field(default_factory=uuid4)
    aggregate_type: str = ""
    aggregate_id: str = ""
    event_type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: datetime | None = None
    attempts: int = 0


class OutboxPublisher:
    """Background-publisher: читает unpublished events и публикует
    в FastStream broker (Kafka/Rabbit — C5 унификация).

    Полная реализация требует:
    - Alembic миграция таблицы outbox_events.
    - LISTEN/NOTIFY Postgres (для low-latency) либо periodic polling.
    - Backoff + max_attempts + DLQ.

    Здесь — scaffold с минимальным интерфейсом (publish + mark_published).
    """

    def __init__(self, *, batch_size: int = 100, poll_interval: float = 1.0) -> None:
        self.batch_size = batch_size
        self.poll_interval = poll_interval

    async def publish_batch(self, events: list[OutboxEvent]) -> list[UUID]:
        """Публикует batch в broker, возвращает published IDs.

        В scaffold-реализации ставит stub: публикация делегируется
        FastStream-producer-у через ``app.infrastructure.clients.messaging.kafka``
        (миграция на FastStream — C5 follow-up).
        """
        from app.infrastructure.eventing.cloudevents import envelope

        published: list[UUID] = []
        for event in events:
            ce = envelope(
                event_type=event.event_type,
                source=f"outbox/{event.aggregate_type}",
                subject=event.aggregate_id,
                data=event.payload,
            )
            try:
                # TODO(C5-follow-up): перенести на FastStream producer
                from app.infrastructure.clients.messaging.kafka import (  # type: ignore[import-not-found]
                    get_kafka_producer,
                )

                producer = get_kafka_producer()
                await producer.send(event.event_type, value=ce, headers=event.headers)
                published.append(event.id)
                event.published_at = datetime.now(timezone.utc)
            except Exception as exc:
                event.attempts += 1
                logger.warning(
                    "Outbox publish failed [attempts=%d]: %s %s",
                    event.attempts,
                    event.id,
                    exc,
                )
        return published
