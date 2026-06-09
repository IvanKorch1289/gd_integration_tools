"""Unit-тесты count_stuck_pending_by_transport (S80 W3, ND-001 step 3).

Использует in-memory SQLite + inline query (тот же pattern что
test_stuck_detection.py). Production function (count_stuck_pending_by_transport)
тестируется в integration tests с real Postgres.

Проверяют:

1. threshold=300 (de facto default).
2. Mixed transport counts → correct dict.
3. Non-stuck messages excluded (status != pending, retry > 0, fresh).
4. group_by transport — multiple transports в одном call.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest_asyncio
from sqlalchemy import func, insert, select
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


def _stuck_row(transport: str, age_seconds: int = 600) -> dict[str, Any]:
    """Build row that should be counted as stuck by threshold=300."""
    now = datetime.now(UTC)
    return {
        "topic": f"t_{transport}",
        "payload": {},
        "headers": {},
        "status": "pending",
        "retry_count": 0,
        "created_at": now - timedelta(seconds=age_seconds),
        "next_attempt_at": now - timedelta(seconds=age_seconds // 2),
        "transport": transport,
    }


async def _count_stuck_by_transport_inline(
    session: AsyncSession, *, threshold_seconds: int
) -> dict[str, int]:
    """Inline replica of count_stuck_pending_by_transport (for SQLite tests).

    Production version in src.backend.infrastructure.repositories.outbox uses
    main_session_manager (Postgres). Для unit tests на SQLite делаем inline
    replica с тем же SQL pattern.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=threshold_seconds)
    stmt = (
        select(OutboxMessage.transport, func.count())
        .where(OutboxMessage.status == "pending")
        .where(OutboxMessage.created_at < cutoff)
        .where(OutboxMessage.retry_count == 0)
        .group_by(OutboxMessage.transport)
    )
    result = await session.execute(stmt)
    return {transport: int(count) for transport, count in result.all()}


async def test_count_stuck_by_transport_mixed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """3 kafka + 2 s3 + 1 rabbitmq → правильный dict."""
    rows = (
        [_stuck_row("kafka") for _ in range(3)]
        + [_stuck_row("s3") for _ in range(2)]
        + [_stuck_row("rabbitmq")]
    )
    async with session_factory() as session:
        for row in rows:
            await session.execute(insert(OutboxMessage).values(**row))  # type: ignore[arg-type]
        await session.commit()
        result = await _count_stuck_by_transport_inline(session, threshold_seconds=300)

    assert result == {"kafka": 3, "s3": 2, "rabbitmq": 1}


async def test_count_stuck_by_transport_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No rows → {}."""
    async with session_factory() as session:
        result = await _count_stuck_by_transport_inline(session, threshold_seconds=300)
    assert result == {}


async def test_count_stuck_by_transport_excludes_non_stuck(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Только status='pending' AND retry_count=0 AND old enough → counted."""
    rows = [
        # 1 stuck kafka — должен попасть
        _stuck_row("kafka", age_seconds=600),
        # sent (excluded)
        {**_stuck_row("kafka", age_seconds=600), "status": "sent"},
        # failed (excluded)
        {**_stuck_row("s3", age_seconds=600), "status": "failed", "retry_count": 5},
        # retry_count > 0 (excluded per ADR-0098 design)
        {**_stuck_row("s3", age_seconds=600), "retry_count": 1},
        # fresh (created < threshold)
        {**_stuck_row("kafka", age_seconds=10)},
    ]
    async with session_factory() as session:
        for row in rows:
            await session.execute(insert(OutboxMessage).values(**row))  # type: ignore[arg-type]
        await session.commit()
        result = await _count_stuck_by_transport_inline(session, threshold_seconds=300)

    # Только 1 stuck kafka
    assert result == {"kafka": 1}


async def test_count_stuck_by_transport_threshold_boundary(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Threshold semantics: old → counted, fresh → not counted.

    Note: реальный "exact boundary" test зависит от microsecond timing —
    row.created_at вычисляется при insert, query.cutoff вычисляется при
    SELECT, между ними проходит время → exact equality ненадёжен в test.
    Тестируем только old (definitely counted) и fresh (definitely not).
    """
    rows = [
        # age=400, threshold=300 → definitely stuck
        _stuck_row("kafka", age_seconds=400),
        # age=10, threshold=300 → definitely fresh
        _stuck_row("s3", age_seconds=10),
    ]
    async with session_factory() as session:
        for row in rows:
            await session.execute(insert(OutboxMessage).values(**row))  # type: ignore[arg-type]
        await session.commit()
        result = await _count_stuck_by_transport_inline(session, threshold_seconds=300)

    assert result == {"kafka": 1}  # s3 excluded как fresh
