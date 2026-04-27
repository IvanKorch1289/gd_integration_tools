"""Outbox-модель для transactional messaging pattern.

Событие записывается в `outbox_messages` в той же транзакции, что и
изменения бизнес-данных. Фоновый worker (``src/workflows/outbox_worker.py``)
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

from src.infrastructure.database.models.base import BaseModel

__all__ = ("OutboxMessage",)


class OutboxMessage(BaseModel):
    """Строка outbox-таблицы.

    Статусы жизненного цикла:

    * ``pending`` — ожидает публикации worker'ом.
    * ``sent`` — успешно опубликовано в брокер.
    * ``failed`` — превышен ``retry_count``, перенесено в DLQ.
    """

    __tablename__ = "outbox_messages"
    # Отключаем SQLAlchemy-Continuum versioning для outbox (не нужен
    # history у служебной таблицы и это даёт лишние записи в *_versions).
    __versioned__ = {"exclude": True}  # type: ignore[assignment]

    topic: Mapped[str] = mapped_column(String(256), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    headers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), index=True
    )
