"""Outbox-pattern Protocol + Fake-реализация.

Контракт for transport-agnostic Dead-Letter Queue (DLQ) + at-least-once
event delivery. Реальная имплементация — `infrastructure/messaging/outbox_dispatcher.py`
(владелец: S5 К2). Этот модуль содержит только контракт + in-memory Fake
для unit-тестов и Streamlit DLQ-replay UI (S6 К5) до момента, когда
S5 К2 закоммитит production-backend.

После S5 К2 завершения DI-контейнер автоматически переключит провайдер на
`OutboxDispatcher` через feature_flag `dlq_unified_enabled`.

Принципы:
    - Protocol — `@runtime_checkable` (можно изоморфно подменять backend);
    - Fake — in-memory, thread-safe-ish (для UI достаточно), без persistence;
    - Все async-методы — Fake тоже async (одинаковая сигнатура).

Связи:
    - feature_flag.dlq_unified_enabled — переключатель Fake → реальный backend;
    - S5 К2 wave [wave:s5/k2-w2-dlq-unified] — реальная имплементация;
    - S6 К5 wave [wave:s6/k5-dlq-replay-ui] — UI consumer.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = (
    "FakeOutbox",
    "OutboxBackend",
    "OutboxEvent",
    "OutboxEventStatus",
)


class OutboxEventStatus(StrEnum):
    """Статус события в Outbox/DLQ.

    Attributes:
        PENDING: ожидает отправки.
        DELIVERED: успешно доставлено.
        DLQ: попало в Dead-Letter Queue после max_attempts.
        RESOLVED: оператор разрешил вручную (manual replay/edit).
    """

    PENDING = "pending"
    DELIVERED = "delivered"
    DLQ = "dlq"
    RESOLVED = "resolved"


class OutboxEvent(BaseModel):
    """Событие Outbox/DLQ — transport-agnostic.

    Attributes:
        event_id: уникальный идентификатор события (uuid4 hex).
        transport: имя транспорта (http/grpc/soap/webhook/kafka/...).
        action: целевое действие/route/topic.
        payload: тело события (произвольный JSON-сериализуемый dict).
        error_class: имя класса последней ошибки (если есть).
        error_message: сообщение последней ошибки (если есть).
        retry_count: количество попыток отправки.
        max_attempts: предельное число попыток до перевода в DLQ.
        status: текущий статус ([OutboxEventStatus]).
        tenant_id: tenant-контекст (для multi-tenancy фильтрации).
        correlation_id: трассировка через [services/observability/tracing].
        created_at: время создания события.
        updated_at: время последнего обновления статуса.
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    transport: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error_class: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    max_attempts: int = 5
    status: OutboxEventStatus = OutboxEventStatus.PENDING
    tenant_id: str | None = None
    correlation_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


@runtime_checkable
class OutboxBackend(Protocol):
    """Контракт Outbox/DLQ backend.

    Реализуется FakeOutbox (in-memory, тесты/UI) и OutboxDispatcher
    (Postgres-table dlq_events, реальный production-backend от S5 К2).
    """

    async def enqueue(self, event: OutboxEvent) -> str:
        """Поставить событие в очередь Outbox.

        Args:
            event: модель события.

        Returns:
            event_id поставленного события.
        """

    async def list_dlq(
        self,
        *,
        transport: str | None = None,
        action: str | None = None,
        error_class: str | None = None,
        tenant_id: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[OutboxEvent]:
        """Получить срез DLQ с опциональной фильтрацией.

        Args:
            transport: фильтр по транспорту.
            action: фильтр по действию/route.
            error_class: фильтр по классу ошибки.
            tenant_id: фильтр по tenant.
            since: события с created_at >= since.
            limit: верхний предел количества.

        Returns:
            последовательность событий, отсортированных по created_at desc.
        """

    async def replay(
        self,
        event_ids: Sequence[str],
        *,
        dry_run: bool = False,
        override_payload: dict[str, Any] | None = None,
    ) -> int:
        """Повторно отправить события из DLQ.

        Args:
            event_ids: идентификаторы событий для replay.
            dry_run: при True — только проверка без реальной отправки.
            override_payload: подменить payload (manual edit-and-replay).

        Returns:
            количество событий, переведённых в PENDING (или прошедших dry-run).
        """

    async def mark_resolved(
        self,
        event_ids: Sequence[str],
        *,
        operator: str | None = None,
        reason: str | None = None,
    ) -> int:
        """Перевести события в RESOLVED (ручное закрытие оператором).

        Args:
            event_ids: идентификаторы событий.
            operator: имя оператора (audit).
            reason: причина manual resolution.

        Returns:
            количество переведённых событий.
        """


class FakeOutbox:
    """In-memory реализация [OutboxBackend] — для unit-тестов и UI до S5 К2 ready.

    Хранит события в `dict[event_id, OutboxEvent]` под asyncio.Lock.
    Не персистирует данные между процессами. Не подходит для production.

    Использование:
        outbox = FakeOutbox()
        await outbox.enqueue(OutboxEvent(transport="http", action="api.send"))
        dlq = await outbox.list_dlq(transport="http")
    """

    def __init__(self) -> None:
        """Инициализация пустого FakeOutbox с asyncio-lock."""
        self._events: dict[str, OutboxEvent] = {}
        self._lock = asyncio.Lock()
        self._replay_log: list[tuple[str, str]] = []  # (event_id, op) audit

    async def enqueue(self, event: OutboxEvent) -> str:
        """Поставить событие — см. [OutboxBackend.enqueue]."""
        async with self._lock:
            self._events[event.event_id] = event
        return event.event_id

    async def list_dlq(
        self,
        *,
        transport: str | None = None,
        action: str | None = None,
        error_class: str | None = None,
        tenant_id: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[OutboxEvent]:
        """Срез DLQ с фильтрами — см. [OutboxBackend.list_dlq]."""
        async with self._lock:
            items = [
                e for e in self._events.values() if e.status == OutboxEventStatus.DLQ
            ]
        if transport is not None:
            items = [e for e in items if e.transport == transport]
        if action is not None:
            items = [e for e in items if e.action == action]
        if error_class is not None:
            items = [e for e in items if e.error_class == error_class]
        if tenant_id is not None:
            items = [e for e in items if e.tenant_id == tenant_id]
        if since is not None:
            items = [e for e in items if e.created_at >= since]
        items.sort(key=lambda e: e.created_at, reverse=True)
        return items[:limit]

    async def replay(
        self,
        event_ids: Sequence[str],
        *,
        dry_run: bool = False,
        override_payload: dict[str, Any] | None = None,
    ) -> int:
        """Replay из DLQ — см. [OutboxBackend.replay]."""
        affected = 0
        async with self._lock:
            for eid in event_ids:
                event = self._events.get(eid)
                if event is None or event.status != OutboxEventStatus.DLQ:
                    continue
                if dry_run:
                    self._replay_log.append((eid, "dry-run"))
                    affected += 1
                    continue
                if override_payload is not None:
                    event.payload = dict(override_payload)
                event.status = OutboxEventStatus.PENDING
                event.retry_count = 0
                event.updated_at = datetime.now(timezone.utc)
                self._replay_log.append((eid, "replay"))
                affected += 1
        return affected

    async def mark_resolved(
        self,
        event_ids: Sequence[str],
        *,
        operator: str | None = None,
        reason: str | None = None,
    ) -> int:
        """Manual resolution — см. [OutboxBackend.mark_resolved]."""
        affected = 0
        now = datetime.now(timezone.utc)
        async with self._lock:
            for eid in event_ids:
                event = self._events.get(eid)
                if event is None or event.status == OutboxEventStatus.RESOLVED:
                    continue
                event.status = OutboxEventStatus.RESOLVED
                event.updated_at = now
                if operator is not None:
                    event.error_message = (
                        f"resolved by={operator} reason={reason or '-'}"
                    )
                self._replay_log.append((eid, f"resolved-by-{operator or 'unknown'}"))
                affected += 1
        return affected

    async def _force_to_dlq(self, event_id: str, error: BaseException) -> bool:
        """Тестовый хелпер — переводит событие в DLQ (имитирует max_attempts).

        Args:
            event_id: идентификатор.
            error: исключение, которое привело к DLQ.

        Returns:
            True если событие найдено и переведено, иначе False.
        """
        async with self._lock:
            event = self._events.get(event_id)
            if event is None:
                return False
            event.status = OutboxEventStatus.DLQ
            event.error_class = type(error).__name__
            event.error_message = str(error)
            event.retry_count = event.max_attempts
            event.updated_at = datetime.now(timezone.utc)
            return True

    async def stats(self) -> dict[str, int]:
        """Сводка по статусам для UI dashboard."""
        async with self._lock:
            buckets: dict[str, int] = defaultdict(int)
            for e in self._events.values():
                buckets[e.status.value] += 1
            return dict(buckets)
