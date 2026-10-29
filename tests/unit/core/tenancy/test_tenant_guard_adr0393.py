"""ADR-0393 — tenant-изоляция DSL-SQL: канон raw SQL и tenant-таблицы.

Закрывает дефекты волны 18:

* **(3)** список tenant-aware таблиц больше не зависит от
  ``configure_mappers()`` — таблицы определяются по колонке ``tenant_id``
  в metadata (включая ``rule_engine_rulesets`` из отдельного
  ``DeclarativeBase``);
* **(6)** канон разбора raw SQL расширен: ``COPY … TO STDOUT``, ``TRUNCATE``
  и ``FROM ONLY <table>`` больше не обходят guard;
* **(4)** DSL-CRUD по tenant-aware таблице требует tenant-предиката —
  ``DbCrudProcessor`` добавляет его сам, а Core-вызов
  (``DatabaseQueryProcessor``) проверяется общим ``guard_raw_sql``;
* **(5)** RLS-скоуп выставляется на соединении из tenant-контекста.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from src.backend.core.tenancy import (
    TenantContext,
    bind_tenant,
    set_tenant,
    unbind_tenant,
)
from src.backend.core.tenancy import sqlalchemy_filter as tf

pytestmark = pytest.mark.unit


class Base(DeclarativeBase):
    """Базовый declarative для изолированных тестовых моделей."""


class Doc(tf.TenantMixin, Base):
    """Tenant-aware сущность для проверки guard'а."""

    __tablename__ = "adr0393_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


@pytest.fixture
def seeded() -> Iterator[Session]:
    """Сессия с tenant-строками и активным tenant-контекстом."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tf.apply_tenant_filter()
    session = Session(engine)
    session.add_all(
        [
            Doc(id=1, name="a-1", tenant_id="tenant-a"),
            Doc(id=2, name="b-1", tenant_id="tenant-b"),
        ]
    )
    session.commit()
    token = bind_tenant(TenantContext(tenant_id="tenant-a"))
    try:
        yield session
    finally:
        unbind_tenant(token)
        session.close()


# ── (3) tenant-таблицы из metadata ────────────────────────────────────────


def test_tenant_aware_tables_include_metadata_tables() -> None:
    """Tenant-таблица видна guard'у по колонке ``tenant_id`` в metadata."""
    tables = tf.tenant_aware_tables()

    assert "adr0393_docs" in tables


def test_tenant_aware_tables_include_rule_engine_rulesets() -> None:
    """``rule_engine_rulesets`` — tenant-aware таблица из отдельного base.

    Раньше она попадала в реестр только после ``configure_mappers()``, и
    запрос к ней до конфигурации **не блокировался** (кросс-tenant чтение
    на БД без RLS).
    """
    tables = tf.tenant_aware_tables()

    assert "rule_engine_rulesets" in tables


def test_tenant_aware_tables_do_not_require_mapper_configuration() -> None:
    """Реестр tenant-таблиц не зависит от состояния mapper'ов.

    Проверяется на «свежей» сессии: подменяем реестр классов пустым и
    убеждаемся, что таблица из metadata всё равно найдена.
    """
    saved = set(tf._TENANT_AWARE_CLASSES)
    tf._TENANT_AWARE_CLASSES.clear()
    try:
        assert "adr0393_docs" in tf.tenant_aware_tables()
    finally:
        tf._TENANT_AWARE_CLASSES.update(saved)


# ── (6) расширенный канон raw SQL ─────────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM adr0393_docs",
        "SELECT * FROM ONLY adr0393_docs",
        "COPY adr0393_docs TO STDOUT",
        "TRUNCATE adr0393_docs",
        "DELETE FROM adr0393_docs WHERE id = 1",
        "UPDATE adr0393_docs SET name = 'x'",
    ],
)
def test_referenced_tables_detects_all_forms(sql: str) -> None:
    """Все формы ссылки на таблицу распознаются каноном разбора."""
    assert "adr0393_docs" in tf.referenced_tables(sql)


def test_raw_sql_guard_blocks_copy_to_stdout(seeded: Session) -> None:
    """``COPY … TO STDOUT`` по tenant-таблице блокируется (ADR-0393)."""
    from sqlalchemy import text

    with pytest.raises(tf.TenantIsolationError):
        seeded.execute(text("COPY adr0393_docs TO STDOUT"))


def test_raw_sql_guard_blocks_truncate(seeded: Session) -> None:
    """``TRUNCATE`` по tenant-таблице блокируется (ADR-0393)."""
    from sqlalchemy import text

    with pytest.raises(tf.TenantIsolationError):
        seeded.execute(text("TRUNCATE adr0393_docs"))


def test_raw_sql_guard_blocks_from_only(seeded: Session) -> None:
    """``FROM ONLY <table>`` блокируется (раньше токен читался как ``ONLY``)."""
    from sqlalchemy import text

    with pytest.raises(tf.TenantIsolationError):
        seeded.execute(text("SELECT * FROM ONLY adr0393_docs"))


def test_raw_sql_guard_allows_scoped_query(seeded: Session) -> None:
    """Явный tenant-предикат — запрос разрешён."""
    from sqlalchemy import text

    rows = seeded.execute(
        text("SELECT id FROM adr0393_docs WHERE tenant_id = :tenant_id"),
        {"tenant_id": "tenant-a"},
    ).all()

    assert [row[0] for row in rows] == [1]


# ── (4) DSL-CRUD tenant-scoped ────────────────────────────────────────────


def test_db_crud_delete_injects_tenant_predicate() -> None:
    """``db_delete`` по tenant-таблице добавляет ``tenant_id`` в WHERE."""
    from src.backend.dsl.engine.processors.db_crud import build_delete_sql

    sql, params = build_delete_sql(
        "adr0393_docs", {"id": 1, "tenant_id": "tenant-a"}, dialect="postgresql"
    )

    assert "tenant_id" in sql
    assert params["tenant_id"] == "tenant-a"


def test_db_crud_without_tenant_context_fails_closed() -> None:
    """Без tenant-контекста CRUD по tenant-таблице падает fail-closed."""
    from src.backend.dsl.engine.exchange import Exchange
    from src.backend.dsl.engine.processors.db_crud import DbCrudProcessor

    processor = DbCrudProcessor("DELETE", "adr0393_docs", where={"id": 1})
    exchange = Exchange()
    exchange.meta.tenant_id = None

    with pytest.raises(tf.TenantIsolationError):
        processor._apply_tenant_scope(
            exchange, "DELETE FROM x", {}, dialect="postgresql"
        )


# ── (5) RLS-скоуп на соединении ───────────────────────────────────────────


def test_set_tenant_scope_skips_non_postgres() -> None:
    """На не-PostgreSQL GUC не выставляется (no-op, без ошибок)."""

    class _Conn:
        dialect = type("D", (), {"name": "sqlite"})()

        def execute(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("SET не должен выполняться на sqlite")

    assert tf.set_tenant_scope(_Conn(), "tenant-a") is False


def test_set_tenant_scope_requires_tenant() -> None:
    """Без tenant-контекста scope не выставляется."""

    class _Conn:
        dialect = type("D", (), {"name": "postgresql"})()

        def execute(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("SET не должен выполняться без tenant")

    assert tf.set_tenant_scope(_Conn(), None) is False
    assert tf.set_tenant_scope(_Conn(), "") is False


def test_orm_filter_still_applies(seeded: Session) -> None:
    """ORM-фильтр по tenant продолжает работать (инвариант)."""
    ids = {row.id for row in seeded.execute(select(Doc)).scalars()}
    assert ids == {1}


# ── (5) RLS-скоуп из flush'а (фоновые пути) ───────────────────────────────


def test_rls_scope_taken_from_flushed_tenant() -> None:
    """Без tenant-контекста scope берётся из tenant'а сохраняемых объектов.

    Фоновые пути (pg-runner, worker) не биндят tenant в ContextVar →
    ``after_begin`` не выставляет ``app.tenant_id`` → на PostgreSQL с
    ``FORCE RLS`` ``INSERT`` отклоняется. Fallback в ``before_flush``
    выставляет scope по tenant'у самих объектов (ADR-0393).
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tf.apply_tenant_filter()
    session = Session(engine)

    applied: list[tuple[str, Any]] = []

    class _Conn:
        dialect = type("D", (), {"name": "postgresql"})()

        def execute(self, statement: Any, params: Any = None) -> None:
            applied.append((str(statement), params))

    session.connection = lambda: _Conn()  # type: ignore[method-assign]
    set_tenant(TenantContext(tenant_id=""))
    session.add(Doc(id=7, name="d-7", tenant_id="tenant-z"))

    tf._ensure_rls_scope_for_flush(session)

    assert applied, "RLS-скоуп не выставлен по tenant'у flush'а"
    assert applied[0][1] == {"tenant_id": "tenant-z"}
    session.close()


def test_rls_scope_not_set_for_multiple_tenants() -> None:
    """Несколько tenant'ов в одном flush → scope не выставляется (fail-closed)."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tf.apply_tenant_filter()
    session = Session(engine)

    applied: list[tuple[str, Any]] = []

    class _Conn:
        dialect = type("D", (), {"name": "postgresql"})()

        def execute(self, statement: Any, params: Any = None) -> None:
            applied.append((str(statement), params))

    session.connection = lambda: _Conn()  # type: ignore[method-assign]
    set_tenant(TenantContext(tenant_id=""))
    session.add(Doc(id=8, name="d-8", tenant_id="tenant-z"))
    session.add(Doc(id=9, name="d-9", tenant_id="tenant-y"))

    tf._ensure_rls_scope_for_flush(session)

    assert not applied
    session.close()
