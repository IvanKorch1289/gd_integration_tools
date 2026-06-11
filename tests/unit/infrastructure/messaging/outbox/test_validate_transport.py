"""Unit-тесты validate_transport + write/write_within_session transport param (S81 W2, ND-001 step 4).

Проверяют:

1. validate_transport:
   - All 7 allowed transports → no error, lowercased.
   - Unknown transport → ValueError с message про ALLOWED_TRANSPORTS.
   - Non-str input → ValueError.
   - Whitespace + uppercase → normalized lowercase.
2. write + write_within_session (inline replica, same pattern):
   - Default transport = 'other'.
   - Explicit transport = 'kafka' (allowed).
   - Invalid transport = 'redis' (not in set) → ValueError.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.backend.infrastructure.database.models.base import mapper_registry
from src.backend.infrastructure.database.models.outbox import OutboxMessage
from src.backend.infrastructure.repositories.outbox import (
    ALLOWED_TRANSPORTS,
    validate_transport,
)

# --------------------------------------------------------------------------- #
# validate_transport
# --------------------------------------------------------------------------- #


def test_validate_transport_all_allowed() -> None:
    """All 7 allowed values → returns lowercased input."""
    for t in ("kafka", "rabbitmq", "nats", "clickhouse", "s3", "webhook", "other"):
        assert validate_transport(t) == t
    assert ALLOWED_TRANSPORTS == frozenset(
        {"kafka", "rabbitmq", "nats", "clickhouse", "s3", "webhook", "other"}
    )


def test_validate_transport_normalizes_case_and_whitespace() -> None:
    """'KAFKA' → 'kafka', '  Kafka  ' → 'kafka'."""
    assert validate_transport("KAFKA") == "kafka"
    assert validate_transport("  Kafka  ") == "kafka"
    assert validate_transport("S3") == "s3"


def test_validate_transport_unknown_raises() -> None:
    """Unknown transport → ValueError со списком allowed."""
    with pytest.raises(ValueError, match="Unknown transport"):
        validate_transport("redis")
    with pytest.raises(ValueError, match="Unknown transport"):
        validate_transport("mq")


def test_validate_transport_non_str_raises() -> None:
    """Non-str input → ValueError."""
    with pytest.raises(ValueError, match="должен быть str"):
        validate_transport(42)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="должен быть str"):
        validate_transport(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# write + write_within_session (inline replica for SQLite tests)
# --------------------------------------------------------------------------- #


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


async def _write_inline(
    session: AsyncSession, *, topic: str, transport: str = "other"
) -> int:
    """Inline replica of write_within_session (S81 W2, validates transport)."""
    transport = validate_transport(transport)
    msg = OutboxMessage(topic=topic, payload={}, headers={}, transport=transport)
    session.add(msg)
    await session.flush()
    return msg.id


async def test_write_within_session_default_transport(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Default transport = 'other' (backwards compat с S80 W3)."""
    async with session_factory() as session:
        msg_id = await _write_inline(session, topic="test.topic")
        await session.commit()
        from sqlalchemy import select as sa_select

        result = await session.execute(
            sa_select(OutboxMessage).where(OutboxMessage.id == msg_id)
        )
        msg = result.scalar_one()
    assert msg.transport == "other"


async def test_write_within_session_explicit_transport(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Explicit transport = 'kafka' → stored as 'kafka'."""
    async with session_factory() as session:
        msg_id = await _write_inline(session, topic="kafka.topic", transport="kafka")
        await session.commit()
        from sqlalchemy import select as sa_select

        result = await session.execute(
            sa_select(OutboxMessage).where(OutboxMessage.id == msg_id)
        )
        msg = result.scalar_one()
    assert msg.transport == "kafka"


async def test_write_within_session_invalid_transport_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Unknown transport 'redis' → ValueError перед insert."""
    async with session_factory() as session:
        with pytest.raises(ValueError, match="Unknown transport"):
            await _write_inline(session, topic="test", transport="redis")


async def test_write_within_session_normalizes_transport(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """'KAFKA' → stored as 'kafka' (lowercased)."""
    async with session_factory() as session:
        msg_id = await _write_inline(session, topic="test", transport="KAFKA")
        await session.commit()
        from sqlalchemy import select as sa_select

        result = await session.execute(
            sa_select(OutboxMessage).where(OutboxMessage.id == msg_id)
        )
        msg = result.scalar_one()
    assert msg.transport == "kafka"
