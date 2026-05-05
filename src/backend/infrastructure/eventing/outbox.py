"""Transactional Outbox Pattern (ADR-011).

Dual-write problem: commit to DB + publish to broker не атомарны. При
падении после commit и до publish (или наоборот) возникают
рассогласования — критично для банковских транзакций.

Решение: в той же транзакции, что меняет бизнес-сущность, записывается
строка в таблицу ``outbox_events``. Отдельный background worker
периодически (или через LISTEN/NOTIFY) читает необработанные события,
публикует в broker и помечает как published.

Wave 3.1 / IL2.1: публикация перенесена на
:class:`StreamClient.publish_to_kafka` — единый FastStream-producer поверх
KafkaRouter. Прежний прямой ``aiokafka`` через ``get_kafka_producer``
признан deprecated и удалён из горячего пути; EOS-транзакционный адаптер
остаётся узким shim-ом до H3_PLUS (см. ADR-013).
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
    в FastStream broker через :class:`StreamClient.publish_to_kafka`.

    Высокоуровневый pipeline:

    * ``publish_batch`` — вход для listener/debounce-пути
      (``outbox_listener.drain_handler``): получает уже загруженные
      :class:`OutboxEvent`-ы, прогоняет каждый через CE-envelope и
      делегирует в ``StreamClient``.
    * ``drain_pending`` — совместимость с ``OutboxListener``. Тонкая
      обёртка, которая читает pending-записи из репозитория
      (по id либо all) и вызывает ``publish_batch``.

    Идемпотентность: дубли возможны в ошибочных сценариях, поэтому
    consumer-сторона должна оставаться идемпотентной (dedupe по ``id``
    CE-envelope). EOS (`transactional_id`) сейчас не используется —
    см. ADR-013 про стратегию до H3_PLUS.
    """

    def __init__(self, *, batch_size: int = 100, poll_interval: float = 1.0) -> None:
        self.batch_size = batch_size
        self.poll_interval = poll_interval

    async def publish_batch(self, events: list[OutboxEvent]) -> list[UUID]:
        """Публикует batch CE-envelope-ов в Kafka через ``StreamClient``.

        Returns:
            Список id успешно опубликованных событий.
        """
        from src.backend.infrastructure.clients.messaging.stream import (
            get_stream_client,
        )
        from src.backend.infrastructure.eventing.cloudevents import envelope

        client = get_stream_client()
        published: list[UUID] = []
        for event in events:
            ce = envelope(
                event_type=event.event_type,
                source=f"outbox/{event.aggregate_type}",
                subject=event.aggregate_id,
                data=event.payload,
            )
            try:
                await client.publish_to_kafka(
                    topic=event.event_type,
                    message=ce,
                    key=event.aggregate_id or None,
                    headers=dict(event.headers),
                )
                published.append(event.id)
                event.published_at = datetime.now(timezone.utc)
            except Exception as exc:  # noqa: BLE001
                event.attempts += 1
                logger.warning(
                    "Outbox publish failed [attempts=%d]: %s %s",
                    event.attempts,
                    event.id,
                    exc,
                )
        return published

    async def drain_pending(self, *, event_ids: list[str] | None = None) -> list[UUID]:
        """Drain-handler для :class:`OutboxListener`.

        Args:
            event_ids: Если передан — drain только указанных записей
                (push-путь из NOTIFY). ``None`` — drain всех pending-ов
                (safety-net polling).

        Returns:
            Список успешно опубликованных ``OutboxEvent.id``.
        """
        from src.backend.infrastructure.repositories import outbox as outbox_repo

        pending = await outbox_repo.fetch_pending(limit=self.batch_size)
        if event_ids is not None:
            wanted = {str(eid) for eid in event_ids}
            pending = [m for m in pending if str(m.id) in wanted]
        if not pending:
            return []

        events = [
            OutboxEvent(
                aggregate_type=(m.headers or {}).get("aggregate_type", ""),
                aggregate_id=(m.headers or {}).get("aggregate_id", "") or str(m.id),
                event_type=m.topic,
                payload=dict(m.payload or {}),
                headers={k: str(v) for k, v in (m.headers or {}).items()},
            )
            for m in pending
        ]
        published = await self.publish_batch(events)

        published_set = {e.id for e in events if e.id in set(published)}
        for msg, ev in zip(pending, events):
            if ev.id in published_set:
                await outbox_repo.mark_sent(msg.id)
            else:
                await outbox_repo.mark_failed(msg.id, error="publish failed (see logs)")
        return list(published_set)
