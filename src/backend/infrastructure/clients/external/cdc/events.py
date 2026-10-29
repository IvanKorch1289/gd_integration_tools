"""S60 W2 — events.py part of cdc decomp.

Classes: CDCEvent, CDCSubscription.

CDCEvent (Pydantic-ish) + CDCSubscription (data classes).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


@dataclass
class CDCEvent:
    """Стандартизированное CDC-событие.

    Attributes:
        operation: INSERT / UPDATE / DELETE / UPSERT.
        table: Имя таблицы-источника.
        timestamp: Момент изменения. Значение приходит «как есть» из
            источника: ISO-8601 строка (polling/listen-notify) или
            ``datetime`` (Kafka). Подмена на ``now()`` запрещена — исходный
            timestamp теряется (ADR-0384).
        profile: Профиль внешней БД.
        new: Новое состояние строки (INSERT/UPDATE).
        old: Старое состояние строки (UPDATE/DELETE).

    """

    operation: str  # INSERT / UPDATE / DELETE / UPSERT
    table: str
    timestamp: str | datetime | None
    profile: str
    new: dict[str, Any] | None = None
    old: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Метод to_dict (см. signature).

        ``datetime`` приводится к ISO-8601 — payload остаётся
        JSON-сериализуемым, исходное значение времени не теряется.
        """
        timestamp = self.timestamp
        if isinstance(timestamp, datetime):
            timestamp = timestamp.isoformat()
        return {
            "operation": self.operation,
            "table": self.table,
            "timestamp": timestamp,
            "profile": self.profile,
            "new": self.new,
            "old": self.old,
        }


@dataclass
class CDCSubscription:
    """Описание подписки на изменения.

    Attributes:
        id: Идентификатор подписки (используется как суффикс consumer-group
            для Kafka — две подписки не делят партиции, ADR-0384).
        profile: Профиль внешней БД.
        tables: Отслеживаемые таблицы.
        strategy: Стратегия обнаружения изменений.
        interval: Интервал polling в секундах.
        batch_size: Максимум событий за итерацию.
        timestamp_column: Колонка с временем изменения (polling).
        channel: Канал PG LISTEN/NOTIFY.
        callback: Async-обработчик событий.
        target_action: Action для диспетчеризации при событии.
        primary_key: Первичный ключ таблицы. Используется для составного
            курсора ``(timestamp, PK)`` — без него строки с одинаковым
            timestamp теряются на границе батча (ADR-0384). ``None`` —
            определить автоматически по первой выборке.
        active: Флаг активности подписки.

    """

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    profile: str = ""
    tables: list[str] = field(default_factory=list)
    strategy: str = "polling"
    interval: float = 5.0
    batch_size: int = 100
    timestamp_column: str = "updated_at"
    channel: str | None = None
    callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    target_action: str | None = None
    primary_key: str | None = None
    active: bool = True
