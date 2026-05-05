"""R2.1 — `CDCSource` Protocol + Pydantic-модели событий.

Generic контракт для Change Data Capture источников. Ядро видит
только Protocol — конкретные backend'ы (`PollCDCBackend`,
`ListenNotifyCDCBackend`, `DebeziumEventsCDCBackend`) живут в
``infrastructure/cdc/`` и подключаются через DI.

Семантика курсора:
* ``cursor`` — opaque str (timestamp / LSN / Kafka offset / etc.).
* ``subscribe()`` стартует с ``start_cursor`` или с self-resumed
  cursor backend'а.
* ``ack(cursor)`` — фиксирует позицию (at-least-once).
* ``replay(start, end)`` — повторное чтение для recovery.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("CDCCursor", "CDCEvent", "CDCOperation", "CDCSource", "FakeCDCSource")


CDCOperation = Literal["INSERT", "UPDATE", "DELETE", "UPSERT", "TRUNCATE"]
"""Тип операции CDC. ``UPSERT`` — для polling-backend'ов, не различающих
INSERT/UPDATE."""


class CDCCursor(BaseModel):
    """Opaque-курсор для resume / replay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str = Field(min_length=1)
    backend: str = Field(min_length=1)


class CDCEvent(BaseModel):
    """Стандартизированное CDC-событие.

    `new` / `old` — состояние записи после/до операции:
    * INSERT: только `new`.
    * UPDATE/UPSERT: `new` (обязательно), `old` (опционально, при
      enable_old_state в backend'е).
    * DELETE: только `old`.
    * TRUNCATE: оба None.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: CDCOperation
    source: str = Field(min_length=1)
    table: str = Field(min_length=1)
    timestamp: datetime
    cursor: CDCCursor
    new: dict[str, Any] | None = None
    old: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class CDCSource(Protocol):
    """Generic CDC-источник."""

    async def subscribe(
        self, *, tables: list[str], start_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Подписаться на изменения; вернуть async-итератор событий.

        :param tables: список целевых таблиц/коллекций/топиков.
        :param start_cursor: позиция начала; ``None`` = с
            backend-специфичной точки (latest / current / 0).
        """
        ...

    async def ack(self, cursor: CDCCursor) -> None:
        """Зафиксировать позицию (at-least-once семантика)."""
        ...

    async def replay(
        self, *, start_cursor: CDCCursor, end_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Повторное чтение событий в диапазоне (для recovery / audit)."""
        ...

    async def close(self) -> None:
        """Закрыть источник, освободить connection / consumer."""
        ...


class FakeCDCSource(CDCSource):
    """In-memory CDC-источник для тестов pipeline'ов.

    Принимает заранее заготовленный список событий и эмитит их
    через `subscribe()`. `ack()` записывает позиции в журнал.
    """

    def __init__(self, *, events: list[CDCEvent]) -> None:
        """Параметры:

        :param events: события, которые `subscribe()` отдаст по порядку.
        """
        self._events = list(events)
        self.acked: list[CDCCursor] = []
        self.closed = False

    async def subscribe(
        self, *, tables: list[str], start_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Эмитит подготовленные события в порядке списка.

        Фильтрует по `tables`; если `start_cursor` задан — пропускает
        события до и включая `start_cursor.value`.
        """
        skip_until: str | None = start_cursor.value if start_cursor else None
        skipping = skip_until is not None
        for ev in self._events:
            if ev.table not in tables:
                continue
            if skipping:
                if ev.cursor.value == skip_until:
                    skipping = False
                continue
            yield ev

    async def ack(self, cursor: CDCCursor) -> None:
        """Записать `cursor` в журнал."""
        self.acked.append(cursor)

    async def replay(
        self, *, start_cursor: CDCCursor, end_cursor: CDCCursor | None = None
    ) -> AsyncIterator[CDCEvent]:
        """Эмитит события из заготовленного журнала в диапазоне курсоров."""
        in_range = False
        for ev in self._events:
            if not in_range and ev.cursor.value == start_cursor.value:
                in_range = True
            if in_range:
                yield ev
                if end_cursor is not None and ev.cursor.value == end_cursor.value:
                    return

    async def close(self) -> None:
        """Пометить источник закрытым."""
        self.closed = True
