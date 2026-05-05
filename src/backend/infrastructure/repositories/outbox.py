"""Репозиторий outbox-сообщений.

Предоставляет минимальный CRUD для transactional outbox pattern:

* :func:`write` — добавление нового сообщения (вызывается бизнес-логикой
  в той же транзакции, что и бизнес-изменения).
* :func:`fetch_pending` — выборка сообщений для публикации worker'ом.
* :func:`mark_sent` / :func:`mark_failed` — обновление статуса после
  попытки публикации.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.infrastructure.database.models.outbox import OutboxMessage
from src.backend.infrastructure.database.session_manager import main_session_manager

__all__ = ("write", "fetch_pending", "mark_sent", "mark_failed", "write_within_session")


async def write_within_session(
    session: AsyncSession,
    *,
    topic: str,
    payload: dict[str, Any],
    headers: dict[str, Any] | None = None,
) -> int:
    """Записывает outbox-сообщение в уже открытой сессии.

    Предназначено для вызова из бизнес-логики, которая управляет
    транзакцией сама — гарантирует atomic-запись с бизнес-данными.

    Returns:
        ID созданной записи.
    """
    msg = OutboxMessage(topic=topic, payload=payload, headers=headers or {})
    session.add(msg)
    await session.flush()  # чтобы получить id без commit
    return msg.id


async def write(
    *, topic: str, payload: dict[str, Any], headers: dict[str, Any] | None = None
) -> int:
    """Автономная запись в outbox (если у вызывающего кода нет своей сессии).

    Открывает и коммитит собственную транзакцию.
    """
    async with main_session_manager.transaction() as session:
        return await write_within_session(
            session, topic=topic, payload=payload, headers=headers
        )


async def fetch_pending(limit: int = 100) -> list[OutboxMessage]:
    """Возвращает сообщения готовые к публикации.

    Фильтр: ``status='pending'`` и ``next_attempt_at <= now``. Сортировка
    по ``created_at`` — FIFO. Limit защищает worker от OOM при большом
    backlog'е.
    """
    now = datetime.now(timezone.utc)
    async with main_session_manager.create_session() as session:
        stmt = (
            select(OutboxMessage)
            .where(OutboxMessage.status == "pending")
            .where(OutboxMessage.next_attempt_at <= now)
            .order_by(OutboxMessage.created_at)
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def mark_sent(message_id: int) -> None:
    """Помечает сообщение как успешно опубликованное."""
    now = datetime.now(timezone.utc)
    async with main_session_manager.transaction() as session:
        await session.execute(
            update(OutboxMessage)
            .where(OutboxMessage.id == message_id)
            .values(status="sent", published_at=now)
        )


async def mark_failed(
    message_id: int, error: str, *, max_retries: int = 5, backoff_seconds: int = 60
) -> None:
    """Инкрементирует retry_count, либо переводит в ``failed`` при исчерпании лимита.

    Args:
        message_id: Идентификатор outbox-записи.
        error: Текст ошибки публикации (обрезается до 1024 символов).
        max_retries: Предел повторов до перевода в финальный ``failed``.
        backoff_seconds: База экспоненциального backoff.
    """
    async with main_session_manager.transaction() as session:
        result = await session.execute(
            select(OutboxMessage).where(OutboxMessage.id == message_id)
        )
        msg = result.scalar_one_or_none()
        if msg is None:
            return

        msg.retry_count += 1
        msg.last_error = error[:1024]
        if msg.retry_count >= max_retries:
            msg.status = "failed"
        else:
            # Экспоненциальный backoff: 60с, 120с, 240с, 480с, …
            delay = backoff_seconds * (2 ** (msg.retry_count - 1))
            msg.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
