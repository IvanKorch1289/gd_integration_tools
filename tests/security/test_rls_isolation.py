"""Sprint 21 W1 — PostgreSQL Row-Level Security isolation tests.

Источник: PLAN.md V22.2 §4 + ADR-NEW-12 + gap-analysis/DEEP-RESEARCH-2026-05-20.md.
Закрывает: B-03 cache poisoning + G-08 RLS missing.

Сценарии (5 штук, 4 pass + 1 xfail):
    1. cache poisoning attempt — tenant A пытается SELECT строки tenant B
       через прямой ``WHERE tenant_id = '<other>'`` фильтр. RLS должен вернуть
       0 строк (USING исключает все non-matching tenant_id).
    2. cross-BU SELECT без WHERE filter — должен вернуть только tenant A
       строки (RLS auto-filter).
    3. WHERE filter bypass через UNION — RLS работает на каждой ветке UNION
       (PostgreSQL применяет policy на table-level).
    4. SET LOCAL пропущен (regression test) — ``current_setting('app.tenant_id', true)``
       возвращает ``NULL``, policy блокирует все строки.
    5. SUPERUSER override — bypassrls=true позволяет видеть все строки
       (xfail без testkit-фикстуры).

Условие запуска: интеграция с Postgres. Тесты помечены
``@pytest.mark.requires_postgres`` и skip при отсутствии connection string.
"""

from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


def _postgres_dsn() -> str | None:
    """DSN для integration test Postgres (TestContainers / staging)."""
    return os.environ.get("S21_TEST_PG_DSN") or os.environ.get("DATABASE_URL")


requires_postgres = pytest.mark.skipif(
    _postgres_dsn() is None,
    reason="S21_TEST_PG_DSN или DATABASE_URL не задан — нужен real Postgres для RLS",
)


@pytest_asyncio.fixture(scope="module")
async def pg_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Async-sessionmaker для тестов RLS.

    Engine создаётся per-module; tear-down закрывает соединения.
    """
    dsn = _postgres_dsn()
    if dsn is None:
        pytest.skip("Postgres DSN отсутствует")
    engine = create_async_engine(dsn)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def populated_table(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[str, str]]:
    """Создаёт временную таблицу с RLS и заполняет тестовыми данными.

    Возвращает (tenant_a, tenant_b) — оба известны вне RLS-контекста.
    """
    tenant_a = f"a_{uuid.uuid4().hex[:8]}"
    tenant_b = f"b_{uuid.uuid4().hex[:8]}"
    table = f"rls_test_{uuid.uuid4().hex[:8]}"

    async with pg_session_factory() as session:
        # Setup: создаём временную таблицу с RLS-политикой
        await session.execute(text(f"""
            CREATE TABLE {table} (
                id SERIAL PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                payload TEXT
            )
        """))
        await session.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        await session.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        await session.execute(text(f"""
            CREATE POLICY p_{table} ON {table}
                USING (tenant_id = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """))
        # Bypass RLS для seed через admin SET app.tenant_id
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, false)"),
            {"t": tenant_a},
        )
        await session.execute(
            text(f"INSERT INTO {table} (tenant_id, payload) VALUES (:t, 'A1')"),
            {"t": tenant_a},
        )
        await session.execute(
            text(f"INSERT INTO {table} (tenant_id, payload) VALUES (:t, 'A2')"),
            {"t": tenant_a},
        )
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, false)"),
            {"t": tenant_b},
        )
        await session.execute(
            text(f"INSERT INTO {table} (tenant_id, payload) VALUES (:t, 'B1')"),
            {"t": tenant_b},
        )
        await session.commit()

    try:
        yield (tenant_a, tenant_b, table)
    finally:
        async with pg_session_factory() as cleanup:
            await cleanup.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            await cleanup.commit()


@requires_postgres
async def test_rls_blocks_explicit_other_tenant_select(
    pg_session_factory: async_sessionmaker[AsyncSession],
    populated_table: tuple[str, str, str],
) -> None:
    """Scenario 1: cache-poisoning attempt — tenant A → WHERE tenant_id = B.

    RLS-policy ``USING (tenant_id = current_setting(...))`` отфильтрует все
    строки с другим tenant_id — даже при явном WHERE filter.
    """
    tenant_a, tenant_b, table = populated_table
    async with pg_session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": tenant_a},
        )
        result = await session.execute(
            text(f"SELECT payload FROM {table} WHERE tenant_id = :other"),
            {"other": tenant_b},
        )
        rows = result.scalars().all()
        assert rows == [], (
            f"RLS должен блокировать чужой tenant_id, получено: {rows}"
        )


@requires_postgres
async def test_rls_filters_cross_bu_select_without_where(
    pg_session_factory: async_sessionmaker[AsyncSession],
    populated_table: tuple[str, str, str],
) -> None:
    """Scenario 2: cross-BU SELECT без WHERE — должен вернуть только tenant A."""
    tenant_a, _tenant_b, table = populated_table
    async with pg_session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": tenant_a},
        )
        result = await session.execute(text(f"SELECT payload FROM {table}"))
        rows = sorted(result.scalars().all())
        assert rows == ["A1", "A2"], (
            f"RLS должен вернуть только tenant A строки, получено: {rows}"
        )


@requires_postgres
async def test_rls_handles_union_bypass_attempt(
    pg_session_factory: async_sessionmaker[AsyncSession],
    populated_table: tuple[str, str, str],
) -> None:
    """Scenario 3: UNION bypass attempt — RLS работает на каждой ветке."""
    tenant_a, _tenant_b, table = populated_table
    async with pg_session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": tenant_a},
        )
        result = await session.execute(
            text(
                f"SELECT payload FROM {table} WHERE id = 1 "
                f"UNION ALL SELECT payload FROM {table} WHERE id IN (2, 3)"
            )
        )
        rows = sorted(result.scalars().all())
        # Только tenant A — id 1, 2 (id 3 принадлежит tenant B)
        assert "B1" not in rows, (
            f"UNION не должен утечь tenant B данные через RLS, получено: {rows}"
        )


@requires_postgres
async def test_rls_blocks_when_set_local_missing(
    pg_session_factory: async_sessionmaker[AsyncSession],
    populated_table: tuple[str, str, str],
) -> None:
    """Scenario 4: regression — без SET LOCAL запрос возвращает 0 строк.

    ``current_setting('app.tenant_id', true)`` без SET возвращает NULL,
    policy ``USING (tenant_id = NULL)`` = FALSE → RLS блокирует все строки.
    """
    _tenant_a, _tenant_b, table = populated_table
    async with pg_session_factory() as session:
        # Не вызываем set_config — namespace `app.tenant_id` не определён
        result = await session.execute(text(f"SELECT payload FROM {table}"))
        rows = result.scalars().all()
        assert rows == [], (
            f"Без SET LOCAL RLS должен блокировать все строки, получено: {rows}"
        )


@pytest.mark.xfail(
    reason="SUPERUSER bypass требует роли с BYPASSRLS=true (testkit fixture отсутствует)",
    strict=False,
)
@requires_postgres
async def test_rls_superuser_bypass(
    pg_session_factory: async_sessionmaker[AsyncSession],
    populated_table: tuple[str, str, str],
) -> None:
    """Scenario 5: SUPERUSER override — bypassrls видит все строки.

    Xfail до создания testkit-фикстуры (S22 carryover) с явным GRANT BYPASSRLS.
    """
    _tenant_a, _tenant_b, table = populated_table
    async with pg_session_factory() as session:
        result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
        count = result.scalar_one()
        assert count == 3, "SUPERUSER должен видеть все 3 строки"
