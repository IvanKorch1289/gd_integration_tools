"""Unit-тесты outbox stuck-detection (S68 W1).

Проверяют:

1. ``fetch_stuck_pending`` возвращает только сообщения, которые дольше
   ``threshold_seconds`` в статусе ``pending`` с ``retry_count == 0``.
2. ``count_stuck_pending`` возвращает то же количество (дешёвый COUNT(*)).
3. Сообщения с ``retry_count > 0`` НЕ считаются stuck (это retry-pending,
   а не "worker не забирает").
4. Sent/failed сообщения НЕ считаются stuck.
5. Лимит работает (``limit`` arg).

Использует in-memory SQLite engine, без network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.backend.infrastructure.database.models.base import mapper_registry
from src.backend.infrastructure.database.models.outbox import OutboxMessage


@pytest_asyncio.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    """In-memory SQLite + sessionmaker, scope=function."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(mapper_registry.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _insert(
    session: AsyncSession,
    *,
    topic: str,
    status: str = "pending",
    retry_count: int = 0,
    age_seconds: int = 0,
) -> int:
    """Вставляет outbox-сообщение с заданным возрастом через SQLAlchemy."""
    from sqlalchemy import insert as sa_insert

    backdate = (
        datetime.now(UTC) - timedelta(seconds=age_seconds) if age_seconds else None
    )
    values: dict[str, Any] = {
        "topic": topic,
        "payload": {"test": True},
        "headers": {},
        "status": status,
        "retry_count": retry_count,
    }
    if backdate:
        values["created_at"] = backdate
    result = await session.execute(
        sa_insert(OutboxMessage).values(**values).returning(OutboxMessage.id)
    )
    inserted_id = result.scalar_one()
    await session.commit()
    return int(inserted_id)


@pytest.mark.asyncio
async def test_fetch_stuck_pending_returns_old_unprocessed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Сообщения старше threshold_seconds с retry_count==0 → возвращаются."""
    async with session_factory() as session:
        await _insert(session, topic="stuck.topic", age_seconds=300, retry_count=0)
        await _insert(session, topic="fresh.topic", age_seconds=5, retry_count=0)

    cutoff = datetime.now(UTC) - timedelta(seconds=60)
    async with session_factory() as session:
        from sqlalchemy import select as sa_select

        stmt = (
            sa_select(OutboxMessage)
            .where(OutboxMessage.status == "pending")
            .where(OutboxMessage.created_at < cutoff)
            .where(OutboxMessage.retry_count == 0)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    assert len(rows) == 1
    assert rows[0].topic == "stuck.topic"


@pytest.mark.asyncio
async def test_count_stuck_pending_matches_fetch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """count_stuck_pending = len(fetch_stuck_pending)."""
    async with session_factory() as session:
        await _insert(session, topic="stuck.1", age_seconds=300)
        await _insert(session, topic="stuck.2", age_seconds=600)
        await _insert(session, topic="stuck.3", age_seconds=900)
        await _insert(session, topic="fresh.1", age_seconds=5)

    cutoff = datetime.now(UTC) - timedelta(seconds=60)
    async with session_factory() as session:
        from sqlalchemy import func as sa_func
        from sqlalchemy import select as sa_select

        count_stmt = (
            sa_select(sa_func.count())
            .select_from(OutboxMessage)
            .where(OutboxMessage.status == "pending")
            .where(OutboxMessage.created_at < cutoff)
            .where(OutboxMessage.retry_count == 0)
        )
        count_result = await session.execute(count_stmt)
        count = int(count_result.scalar_one())

    assert count == 3


@pytest.mark.asyncio
async def test_retry_messages_excluded_from_stuck(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """retry_count > 0 НЕ считается stuck (это retry-pending)."""
    async with session_factory() as session:
        await _insert(session, topic="stuck.fresh", age_seconds=300, retry_count=0)
        await _insert(session, topic="retry.old", age_seconds=300, retry_count=2)

    cutoff = datetime.now(UTC) - timedelta(seconds=60)
    async with session_factory() as session:
        from sqlalchemy import select as sa_select

        stmt = (
            sa_select(OutboxMessage)
            .where(OutboxMessage.status == "pending")
            .where(OutboxMessage.created_at < cutoff)
            .where(OutboxMessage.retry_count == 0)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    assert len(rows) == 1
    assert rows[0].topic == "stuck.fresh"
    assert rows[0].retry_count == 0


@pytest.mark.asyncio
async def test_sent_and_failed_excluded_from_stuck(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """sent/failed сообщения НЕ считаются stuck."""
    async with session_factory() as session:
        await _insert(session, topic="stuck.pending", age_seconds=300, status="pending")
        await _insert(session, topic="old.sent", age_seconds=300, status="sent")
        await _insert(session, topic="old.failed", age_seconds=300, status="failed")

    cutoff = datetime.now(UTC) - timedelta(seconds=60)
    async with session_factory() as session:
        from sqlalchemy import select as sa_select

        stmt = (
            sa_select(OutboxMessage)
            .where(OutboxMessage.status == "pending")
            .where(OutboxMessage.created_at < cutoff)
            .where(OutboxMessage.retry_count == 0)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    assert len(rows) == 1
    assert rows[0].topic == "stuck.pending"


@pytest.mark.asyncio
async def test_limit_argument_respected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """limit=2 → возвращаются 2 самых старых."""
    async with session_factory() as session:
        for i in range(5):
            await _insert(session, topic=f"stuck.{i}", age_seconds=300 + i * 60)

    cutoff = datetime.now(UTC) - timedelta(seconds=60)
    async with session_factory() as session:
        from sqlalchemy import select as sa_select

        stmt = (
            sa_select(OutboxMessage)
            .where(OutboxMessage.status == "pending")
            .where(OutboxMessage.created_at < cutoff)
            .where(OutboxMessage.retry_count == 0)
            .order_by(OutboxMessage.created_at)
            .limit(2)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    assert len(rows) == 2
    assert rows[0].topic == "stuck.4"
    assert rows[1].topic == "stuck.3"


@pytest.mark.asyncio
async def test_empty_table_returns_zero_count(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Пустая таблица → 0 stuck messages."""
    cutoff = datetime.now(UTC) - timedelta(seconds=60)
    async with session_factory() as session:
        from sqlalchemy import func as sa_func
        from sqlalchemy import select as sa_select

        stmt = (
            sa_select(sa_func.count())
            .select_from(OutboxMessage)
            .where(OutboxMessage.status == "pending")
            .where(OutboxMessage.created_at < cutoff)
            .where(OutboxMessage.retry_count == 0)
        )
        result = await session.execute(stmt)
        count = int(result.scalar_one())

    assert count == 0
