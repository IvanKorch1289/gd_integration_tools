"""Outbox-модель для transactional messaging pattern.

Событие записывается в `outbox_messages` в той же транзакции, что и
изменения бизнес-данных. Фоновый worker (``src/backend/workflows/outbox_worker.py`` (deprecated, moved to
    ``src/backend/infrastructure/workflow/outbox_worker.py`` per
    master prompt v8 P2-7))
периодически читает записи со ``status='pending'`` и публикует их в брокер
(Kafka/RabbitMQ/Redis Streams), затем помечает ``status='sent'``.

Это гарантирует at-least-once доставку даже при падении приложения между
коммитом бизнес-транзакции и публикацией в брокер.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel

__all__ = ("OutboxMessage",)


class OutboxMessage(BaseModel):
    """Строка outbox-таблицы.

    Статусы жизненного цикла:

    * ``pending`` — ожидает публикации worker'ом.
    * ``sent`` — успешно опубликовано в брокер.
    * ``failed`` — превышен ``retry_count``, перенесено в DLQ.
    """

    __tablename__ = "outbox_messages"
    # Отключаем SQLAlchemy-Continuum versioning для outbox: служебная таблица
    # не нуждается в history. Используется задокументированный ключ
    # ``versioning: False`` (sqlalchemy-continuum), а не ``exclude: True`` —
    # последний ожидает iterable колонок и приводит к TypeError в
    # ``is_excluded_property`` (``key in True``).
    __versioned__ = {"versioning": False}

    topic: Mapped[str] = mapped_column(String(256), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    headers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # S80 W3 (ND-001 step 1): transport tag для per-transport breakdown.
    # Values: "kafka" | "rabbitmq" | "nats" | "clickhouse" | "s3" | "webhook" | "other".
    # Default='other' для backwards-compat с existing rows (pre-migration).
    transport: Mapped[str] = mapped_column(String(32), default="other", index=True)

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), index=True
    )

    # S72 W1 (TD-S64-W1, ADR-0087): per-row claim metadata.
    # ``claimed_by`` = worker_id, ``claimed_at`` = claim moment,
    # ``claimed_until`` = deadline после которого sweeper может
    # reset'нуть row в ``pending`` (lease TTL). Все 3 nullable для
    # backwards-compat с existing rows.
    claimed_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claimed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
