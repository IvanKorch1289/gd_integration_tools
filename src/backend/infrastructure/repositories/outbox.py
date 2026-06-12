"""Репозиторий outbox-сообщений.

Предоставляет минимальный CRUD для transactional outbox pattern:

* :func:`write` — добавление нового сообщения (вызывается бизнес-логикой
  в той же транзакции, что и бизнес-изменения).
* :func:`fetch_pending` — выборка сообщений для публикации worker'ом.
* :func:`fetch_stuck_pending` — выборка "застрявших" pending-сообщений
  (created_at < now - threshold_seconds) для stuck-detection алертов.
* :func:`count_stuck_pending` — быстрый подсчёт stuck-сообщений для
  Prometheus gauge.
* :func:`count_stuck_pending_by_transport` — per-transport breakdown
  для per-transport Grafana panels (S80 W3, ND-001 step 3).
* :func:`mark_sent` / :func:`mark_failed` — обновление статуса после
  попытки публикации.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.infrastructure.database.models.outbox import OutboxMessage
from src.backend.infrastructure.database.session_manager import main_session_manager

__all__ = (
    "ALLOWED_TRANSPORTS",
    "claim_pending",
    "count_stuck_pending",
    "count_stuck_pending_by_transport",
    "fetch_pending",
    "fetch_stuck_pending",
    "mark_failed",
    "mark_sent",
    "validate_transport",
    "write",
    "write_within_session",
)

#: S81 W2 (ND-001 step 4). Allowed values для ``OutboxMessage.transport``.
#: "other" — fallback для existing rows (pre-migration) и unknown transports.
#: Adding a new transport: extend this set + add OutboxBackend writer для него.
ALLOWED_TRANSPORTS: frozenset[str] = frozenset(
    {"kafka", "rabbitmq", "nats", "clickhouse", "s3", "webhook", "other"}
)


def validate_transport(transport: str) -> str:
    """Валидирует значение transport field (S81 W2, ND-001 step 4).

    Args:
        transport: имя транспорта для проверки.

    Returns:
        Same transport (lowercased) если валидно.

    Raises:
        ValueError: если transport не в ALLOWED_TRANSPORTS.

    Note: normalization (lowercase) обеспечивает consistent label values
    для Prometheus (per-transport gauge), иначе "Kafka" и "kafka" дают
    2 разных label'а.
    """
    if not isinstance(transport, str):
        raise ValueError(f"transport должен быть str, got {type(transport).__name__}")
    transport = transport.strip().lower()
    if transport not in ALLOWED_TRANSPORTS:
        raise ValueError(
            f"Unknown transport: {transport!r}. "
            f"Allowed: {sorted(ALLOWED_TRANSPORTS)}. "
            f"Add to ALLOWED_TRANSPORTS если нужен новый transport."
        )
    return transport


async def write_within_session(
    session: AsyncSession,
    *,
    topic: str,
    payload: dict[str, Any],
    headers: dict[str, Any] | None = None,
    transport: str = "other",
) -> int:
    """Записывает outbox-сообщение в уже открытой сессии.

    Предназначено для вызова из бизнес-логики, которая управляет
    транзакцией сама — гарантирует atomic-запись с бизнес-данными.

    Args:
        topic: имя топика/очереди.
        payload: сериализуемый payload (dict).
        headers: optional headers (trace, auth, etc.).
        transport: имя транспорта для per-transport breakdown
            (S81 W2, ND-001 step 4). Default='other' для backwards compat.

    Returns:
        ID созданной записи.
    """
    transport = validate_transport(transport)
    msg = OutboxMessage(
        topic=topic, payload=payload, headers=headers or {}, transport=transport
    )
    session.add(msg)
    await session.flush()  # чтобы получить id без commit
    return msg.id


async def write(
    *,
    topic: str,
    payload: dict[str, Any],
    headers: dict[str, Any] | None = None,
    transport: str = "other",
) -> int:
    """Автономная запись в outbox (если у вызывающего кода нет своей сессии).

    Открывает и коммитит собственную транзакцию.
    """
    async with main_session_manager.transaction() as session:
        return await write_within_session(
            session, topic=topic, payload=payload, headers=headers, transport=transport
        )


async def fetch_pending(limit: int = 100) -> list[OutboxMessage]:
    """Возвращает сообщения готовые к публикации.

    Фильтр: ``status='pending'`` и ``next_attempt_at <= now``. Сортировка
    по ``created_at`` — FIFO. Limit защищает worker от OOM при большом
    backlog'е.

    .. warning::
       **Не multi-instance safe**: N worker'ов, вызывающих параллельно,
       прочтут один и тот же набор строк → дубль публикаций. Для
       multi-instance используй :func:`claim_pending`.

    See :func:`claim_pending` для production path (S64 W1).
    """
    now = datetime.now(UTC)
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


def _advisory_lock_key(worker_id: str) -> int:
    """Deterministic 64-bit int key из ``worker_id`` для ``pg_try_advisory_xact_lock``.

    Использует BLAKE2b-256 с 8-байтовым digest → 64-bit unsigned int
    (Postgres bigint range). Same pattern as
    :func:`src.backend.infrastructure.workflow.pg_runner_internals.event_store._advisory_lock_key`
    — но для outbox.
    """
    digest = hashlib.blake2b(worker_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=False) & 0x7FFFFFFFFFFFFFFF


async def claim_pending(
    limit: int = 100,
    *,
    worker_id: str,
    lease_seconds: int = 300,
) -> list[OutboxMessage]:
    """Multi-instance safe атомарный claim batch pending outbox-сообщений (S64 W1).

    Алгоритм:

    1. ``pg_try_advisory_xact_lock(hash(worker_id))`` — non-blocking try-lock
       per-worker. Если другой worker уже держит lock — возврат ``[]``
       (этот worker skip, попробует следующий tick).
    2. ``UPDATE outbox_messages SET retry_count = retry_count + 1 WHERE id IN
       (SELECT id FROM outbox_messages WHERE status='pending' AND
        next_attempt_at <= now ORDER BY created_at LIMIT :limit
        FOR UPDATE SKIP LOCKED) RETURNING *`` — атомарный claim
       (SELECT-FOR-UPDATE-SKIP-LOCKED предотвращает гонки даже в пределах
       одной сессии/транзакции).
    3. Commit → advisory lock и row locks снимаются.

    Args:
        limit: max messages in batch (default 100).
        worker_id: уникальный ID (UUID, pod-name, hostname). Hash
            используется как advisory lock key.
        lease_seconds: (reserved) lease TTL для будущего S65
            (``status='processing'`` + ``locked_until``). Сейчас
            игнорируется — atomic-claim уже обеспечивает не-дубли
            в пределах одной транзакции.

    Returns:
        List of claimed :class:`OutboxMessage` records (с инкрементированным
        ``retry_count``). ``[]`` если advisory lock не получен (другой
        worker активен) ИЛИ если pending пуст.

    Trade-offs / ограничения:

    * **Advisory lock granularity = per-call, не per-row.** Один worker
      захватывает lock → claim batch → commit. Другой worker в это
      время получает ``[]`` (skip) и попробует на следующем tick.
      Это **batch-level coordination**, не row-level.
    * **После commit row lock released**, ``retry_count`` инкрементирован
      (signal for monitoring), но ``status`` остаётся ``pending``. Если
      worker упадёт между claim и ``mark_sent``, строка будет
      переclaim'нута следующим tick (retry_count уже > 0). Корректно
      для at-least-once семантики.
    * **Полное row-level решение** (с ``status='processing'`` +
      ``locked_until``) — S65+ (требует Alembic-миграцию).
    """
    if not worker_id:
        raise ValueError("worker_id обязателен для claim_pending")

    lock_key = _advisory_lock_key(worker_id)
    now = datetime.now(UTC)
    async with main_session_manager.transaction() as session:
        # 1. Try acquire per-worker advisory lock
        got_lock = bool(
            (
                await session.execute(
                    text("SELECT pg_try_advisory_xact_lock(:k)"),
                    {"k": lock_key},
                )
            ).scalar()
        )
        if not got_lock:
            return []

        # 2. Atomic claim: SELECT FOR UPDATE SKIP LOCKED + UPDATE + RETURNING
        result = await session.execute(
            text(
                """
                UPDATE outbox_messages
                SET retry_count = retry_count + 1
                WHERE id IN (
                    SELECT id FROM outbox_messages
                    WHERE status = 'pending'
                      AND next_attempt_at <= :now
                    ORDER BY created_at
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, topic, payload, headers, status, retry_count,
                          last_error, transport, published_at, next_attempt_at,
                          created_at, updated_at
                """
            ),
            {"now": now, "limit": limit},
        )
        rows = result.fetchall()
        # Преобразуем RawRow → OutboxMessage ORM-объекты
        return [
            OutboxMessage(
                id=row.id,
                topic=row.topic,
                payload=row.payload,
                headers=row.headers or {},
                status=row.status,
                retry_count=row.retry_count,
                last_error=row.last_error,
                transport=row.transport,
                published_at=row.published_at,
                next_attempt_at=row.next_attempt_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]


async def fetch_stuck_pending(
    *, threshold_seconds: int, limit: int = 100
) -> list[OutboxMessage]:
    """Возвращает pending-сообщения, которые "застряли" дольше threshold.

    Stuck-сообщение = ``status='pending'`` AND ``created_at < now() - threshold_seconds``
    AND ``retry_count == 0`` (т.е. ни разу не был обработан worker'ом).

    Используется для:
    * Алертов (Grafana: outbox_stuck_pending_count gauge)
    * Investigation dashboard (что именно застряло, по каким topics)
    * Manual replay после fix worker'а

    Args:
        threshold_seconds: Минимальный возраст "застрявшего" сообщения.
            Рекомендация: ``2 * poll_interval`` (т.е. 2x периода worker'а).
        limit: Защита от OOM при большом backlog'е.

    Returns:
        Список :class:`OutboxMessage` отсортированный по ``created_at`` ASC.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=threshold_seconds)
    async with main_session_manager.create_session() as session:
        stmt = (
            select(OutboxMessage)
            .where(OutboxMessage.status == "pending")
            .where(OutboxMessage.created_at < cutoff)
            .where(OutboxMessage.retry_count == 0)
            .order_by(OutboxMessage.created_at)
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def count_stuck_pending(*, threshold_seconds: int) -> int:
    """Подсчитывает количество "застрявших" pending-сообщений.

    Дешёвый COUNT(*) запрос — используется для Prometheus gauge
    ``outbox_stuck_pending_count`` (sampled раз в N секунд).

    Args:
        threshold_seconds: см. :func:`fetch_stuck_pending`.

    Returns:
        Количество stuck-сообщений. 0 если ни одного.
    """
    if threshold_seconds <= 0:
        raise ValueError("threshold_seconds должен быть > 0")
    cutoff = datetime.now(UTC) - timedelta(seconds=threshold_seconds)
    async with main_session_manager.create_session() as session:
        stmt = (
            select(func.count())
            .select_from(OutboxMessage)
            .where(OutboxMessage.status == "pending")
            .where(OutboxMessage.created_at < cutoff)
            .where(OutboxMessage.retry_count == 0)
        )
        result = await session.execute(stmt)
        return int(result.scalar_one())


async def count_stuck_pending_by_transport(*, threshold_seconds: int) -> dict[str, int]:
    """Per-transport breakdown stuck-pending counts (S80 W3, ND-001 step 3).

    Returns:
        dict {transport: stuck_count} для всех transports с non-zero stuck.
        Транспорты с 0 stuck excluded (Prometheus label cardinality reduction).

    Example:
        {"kafka": 42, "s3": 7}  # только non-zero

    Note: возвращает только non-zero для уменьшения label cardinality.
    Use :func:`count_stuck_pending` для aggregate.
    """
    if threshold_seconds <= 0:
        raise ValueError("threshold_seconds должен быть > 0")
    cutoff = datetime.now(UTC) - timedelta(seconds=threshold_seconds)
    async with main_session_manager.create_session() as session:
        stmt = (
            select(OutboxMessage.transport, func.count())
            .where(OutboxMessage.status == "pending")
            .where(OutboxMessage.created_at < cutoff)
            .where(OutboxMessage.retry_count == 0)
            .group_by(OutboxMessage.transport)
        )
        result = await session.execute(stmt)
        return {transport: int(count) for transport, count in result.all()}


async def mark_sent(message_id: int) -> None:
    """Помечает сообщение как успешно опубликованное."""
    now = datetime.now(UTC)
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
            msg.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
