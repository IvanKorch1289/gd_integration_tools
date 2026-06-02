"""Unit-тесты атомарности transactional outbox-паттерна.

Проверяют главный инвариант DoD-4 Sprint 16:
запись `outbox_messages` происходит в одной транзакции с бизнес-данными.
При rollback откатываются обе записи; при commit — обе сохранены.

Wave: ``[wave:s16/k2-w2-outbox-tx-atomic]``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

pytest.importorskip("aiosqlite")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.backend.infrastructure.database.models.base import mapper_registry
from src.backend.infrastructure.database.models.outbox import OutboxMessage
from src.backend.infrastructure.messaging.outbox.repository import OutboxRepository


@pytest_asyncio.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    """In-memory SQLite engine + sessionmaker для атомарных тестов."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(mapper_registry.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_enqueue_persists_after_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """После commit запись присутствует в БД (golden-path)."""
    async with session_factory() as session, session.begin():
        repo = OutboxRepository(session)
        await repo.enqueue(
            topic="orders.created",
            payload={"order_id": 42, "total": 100},
            headers={"correlation_id": "cid-1"},
        )
    # Новая сессия — независимая транзакция чтения.
    async with session_factory() as reader:
        result = await reader.execute(select(OutboxMessage))
        rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].topic == "orders.created"
    assert rows[0].payload == {"order_id": 42, "total": 100}
    assert rows[0].status == "pending"


@pytest.mark.asyncio
async def test_enqueue_rollback_drops_record(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """При rollback (имитация падения процесса) запись НЕ должна остаться."""

    class DummyBusinessFailure(RuntimeError):
        """Симулируем падение бизнес-логики после enqueue, до commit."""

    with pytest.raises(DummyBusinessFailure):
        async with session_factory() as session, session.begin():
            repo = OutboxRepository(session)
            await repo.enqueue(
                topic="orders.created",
                payload={"order_id": 99},
            )
            # Имитируем падение процесса между enqueue и commit.
            raise DummyBusinessFailure("simulated crash before commit")

    # Чтение в независимой сессии — ничего не должно быть.
    async with session_factory() as reader:
        result = await reader.execute(select(OutboxMessage))
        rows = result.scalars().all()
    assert rows == [], "rollback должен откатывать outbox-запись (dropped=0)"


@pytest.mark.asyncio
async def test_enqueue_default_headers_and_retry_count(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """По умолчанию headers={} и retry_count=0; status=pending."""
    async with session_factory() as session, session.begin():
        repo = OutboxRepository(session)
        msg = await repo.enqueue(topic="t", payload={"a": 1})
        assert msg.id is not None, "flush должен вернуть PK без commit"
        assert msg.headers == {}
        assert msg.retry_count == 0
        assert msg.status == "pending"


@pytest.mark.asyncio
async def test_enqueue_does_not_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """OutboxRepository.enqueue НЕ должен сам коммитить транзакцию.

    Caller отвечает за commit — это база transactional outbox-паттерна.
    """
    async with session_factory() as session:
        # Открываем транзакцию вручную, но НЕ коммитим.
        async with session.begin():
            repo = OutboxRepository(session)
            await repo.enqueue(topic="t", payload={"a": 1})
            # До выхода из begin()-блока запись видна в текущей сессии.
            result = await session.execute(select(OutboxMessage))
            assert len(result.scalars().all()) == 1
            # Имитируем откат:
            await session.rollback()

    # Чтение в новой сессии — записи нет.
    async with session_factory() as reader:
        result = await reader.execute(select(OutboxMessage))
        assert result.scalars().all() == []
