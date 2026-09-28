"""Runtime contract: Postgres erasure against a REAL ``{entity}_pii`` table.

ADR-0347. Прежний ``test_postgres_tenant_enforcement.py`` зависел от
несуществующего модуля ``core.domain.models.privacy_models`` и поэтому
ПОСТОЯННО пропускался («PiiErasureRecord model unavailable in dev env»).
Именно поэтому нерабочий адаптер (``ModuleNotFoundError`` на каждом
erasure) оставался незамеченным, а privacy gate показывал «✅ covered».

Эти тесты self-contained: таблица создаётся в SQLite, поэтому erasure
реально исполняется в dev-окружении.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.backend.core.privacy.delete_data_subject._postgres import (
    PostgresErasureAdapter,
)
from src.backend.core.privacy.delete_data_subject._types import (
    ErasureResultStatus,
    ErasureStrategy,
)
from src.backend.core.privacy.pii_table import pii_table_for_subject

pytestmark = pytest.mark.asyncio

_CREATE_PII = """
CREATE TABLE user_pii (
    id INTEGER PRIMARY KEY,
    entity_id TEXT NOT NULL,
    name TEXT,
    email TEXT,
    phone TEXT,
    anonymized_at TIMESTAMP,
    tenant_id TEXT
)
"""


@pytest.fixture()
async def session_factory() -> Any:
    """SQLite с реально существующей PII-таблицей."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_PII))
        await conn.execute(
            text(
                "INSERT INTO user_pii (entity_id, name, email, phone, tenant_id) "
                "VALUES ('42', 'A', 'a@example.com', '+1', 'tenant-a'),"
                "       ('42', 'B', 'b@example.com', '+2', 'tenant-b'),"
                "       ('99', 'C', 'c@example.com', '+3', 'tenant-a')"
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _rows(session_factory: Any) -> list[tuple[str, str]]:
    async with session_factory() as session:
        res = await session.execute(
            text("SELECT entity_id, tenant_id FROM user_pii ORDER BY id")
        )
        return [(r[0], r[1]) for r in res.all()]


# --------------------------------------------------------------------------
# Table naming / identifier safety
# --------------------------------------------------------------------------


def test_pii_table_name_derivation() -> None:
    """subject_id -> валидированное имя PII-таблицы."""
    assert pii_table_for_subject("user:42") == "user_pii"


@pytest.mark.parametrize(
    "bad", ["user 42", "user;DROP TABLE x", "user-42", "1user:42", "noscope"]
)
def test_pii_table_name_rejects_unsafe_or_malformed(bad: str) -> None:
    """Whitelist entity_type защищает от SQL-инъекции в имени таблицы."""
    with pytest.raises(ValueError):
        pii_table_for_subject(bad)


# --------------------------------------------------------------------------
# Erasure actually runs (regression: ModuleNotFoundError на каждый вызов)
# --------------------------------------------------------------------------


async def test_adapter_executes_instead_of_failing_on_import(
    session_factory: Any,
) -> None:
    """Regression: адаптер падал ModuleNotFoundError на КАЖДОМ erasure."""
    adapter = PostgresErasureAdapter(session_factory=session_factory)
    result = await adapter.execute(
        subject_id="user:99",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="c1",
        tenant_id="tenant-a",
    )
    assert result.status is ErasureResultStatus.SUCCESS, result.error
    assert result.records_affected == 1


async def test_hard_delete_removes_only_matching_tenant(session_factory: Any) -> None:
    """ERASE в tenant-a не трогает запись того же entity_id в tenant-b."""
    adapter = PostgresErasureAdapter(session_factory=session_factory)
    result = await adapter.execute(
        subject_id="user:42",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="c1",
        tenant_id="tenant-a",
    )
    assert result.status is ErasureResultStatus.SUCCESS, result.error
    assert result.records_affected == 1
    # tenant-a/42 удалена; tenant-b/42 (чужой тенант) и tenant-a/99 не тронуты.
    assert await _rows(session_factory) == [("42", "tenant-b"), ("99", "tenant-a")]


async def test_anonymize_nulls_pii_but_keeps_row(session_factory: Any) -> None:
    """ANONYMIZE обнуляет PII, но не удаляет строку."""
    adapter = PostgresErasureAdapter(session_factory=session_factory)
    result = await adapter.execute(
        subject_id="user:42",
        subject_type="user",
        strategy=ErasureStrategy.ANONYMIZE,
        correlation_id="c1",
        tenant_id="tenant-a",
    )
    assert result.status is ErasureResultStatus.SUCCESS, result.error

    async with session_factory() as session:
        res = await session.execute(
            text(
                "SELECT name, email FROM user_pii WHERE entity_id='42' AND tenant_id='tenant-a'"
            )
        )
        row = res.first()
    assert row is not None, "anonymize не должен удалять строку"
    assert row[0] is None and row[1] is None


async def test_missing_session_factory_is_skipped_not_failed() -> None:
    """Без session factory → SKIPPED (явная причина), не FAILED."""
    adapter = PostgresErasureAdapter(session_factory=None)
    result = await adapter.execute(
        subject_id="user:1",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="c1",
    )
    assert result.status is ErasureResultStatus.SKIPPED
    assert "session_factory" in (result.error or "")


async def test_malformed_subject_id_fails_closed(session_factory: Any) -> None:
    """Некорректный subject_id → FAILED с причиной, а не «успех»."""
    adapter = PostgresErasureAdapter(session_factory=session_factory)
    result = await adapter.execute(
        subject_id="not-a-scope",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="c1",
        tenant_id="tenant-a",
    )
    assert result.status is ErasureResultStatus.FAILED
    assert "entity_type" in (result.error or "")


async def test_empty_tenant_fails_closed(session_factory: Any) -> None:
    """Пустой tenant → FAILED: нельзя удалять без доказанных границ.

    Fail-closed (ADR-0347): DELETE без tenant-фильтра стёр бы PII всех
    тенантов с тем же entity_id.
    """
    adapter = PostgresErasureAdapter(session_factory=session_factory)
    result = await adapter.execute(
        subject_id="user:42",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="c1",
        tenant_id="",
    )
    assert result.status is ErasureResultStatus.FAILED
    assert "tenant_id is required" in (result.error or "")
    # Данные не тронуты.
    assert len(await _rows(session_factory)) == 3


async def test_missing_pii_table_fails_closed(session_factory: Any) -> None:
    """Несуществующая PII-таблица → FAILED, а не тихий «успех с 0 строк»."""
    adapter = PostgresErasureAdapter(session_factory=session_factory)
    result = await adapter.execute(
        subject_id="order:1",
        subject_type="order",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="c1",
        tenant_id="tenant-a",
    )
    assert result.status is ErasureResultStatus.FAILED
    assert "order_pii" in (result.error or "")
