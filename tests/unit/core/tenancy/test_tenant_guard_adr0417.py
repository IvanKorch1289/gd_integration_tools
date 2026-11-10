"""ADR-0417 — границы tenant-guard'а: main-контур vs внешние БД.

Закрывает дефекты мультироевого аудита (волна 24, кластер F2):

* **(1) high** — tenant-guard применялся к **внешним** БД: listener на
  глобальном ``Session`` фильтровал raw SQL всех сессий, включая внешние
  профили. Внешний запрос к таблице с tenant-именем (``workflow_instances``)
  отклонялся с ``TenantIsolationError`` — ломались ``db_query_external`` /
  ``jdbc_query`` / ``batch_*``. Фикс: guard применяется ТОЛЬКО к main-контуру;
  внешний контур — отдельный tenant-контур (ADR-0417).
* **(2) high** — guard пропускался без tenant-контекста: raw SQL
  ``text("SELECT ...")`` без tenant'а выполнялся как есть и читал строки
  чужих tenant'ов. Фикс: guard вызывается ВСЕГДА для main-сессий и
  fail-closed закрывает запрос без tenant-скоупа.
* **(3) medium** — extension-таблицы (``orders`` / ``users`` / ``files`` /
  ``orderkinds``) не попадали в ``tenant_aware_tables()``: ORM-модели живут в
  ``extensions/`` и загружаются лениво. Фикс: канонический список
  tenant-таблиц (ADR-0417).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from src.backend.core.tenancy import (
    TenantContext,
    bind_tenant,
    set_tenant,
    unbind_tenant,
)
from src.backend.core.tenancy import sqlalchemy_filter as tf
from src.backend.core.tenancy.tenant_tables import TENANT_TABLES

pytestmark = pytest.mark.unit

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"

#: Таблица с tenant-именем из канонического списка (ORM-модели в ядре нет —
#: динамическое обнаружение её не найдёт, сработает только явный список).
WORKFLOW_INSTANCES_DDL = (
    "CREATE TABLE workflow_instances ("
    "id INTEGER PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL, name VARCHAR(50))"
)


class Base(DeclarativeBase):
    """Базовый declarative для изолированных тестовых моделей."""


class Doc(tf.TenantMixin, Base):
    """Tenant-aware сущность для проверки ORM-фильтра."""

    __tablename__ = "adr0417_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


def _engine_with_workflow_instances() -> "object":
    """Создать sqlite-движок с таблицей ``workflow_instances``.

    Returns:
        Движок с созданной таблицей.
    """
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(WORKFLOW_INSTANCES_DDL))
    return engine


@pytest.fixture
def main_session() -> Iterator[Session]:
    """Сессия main-контура с tenant-контекстом ``tenant-a``.

    Returns:
        Открытая сессия; tenant-guard зарегистрирован (идемпотентно).
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tf.apply_tenant_filter()
    session = Session(engine)
    session.add_all(
        [
            Doc(id=1, name="a-1", tenant_id=TENANT_A),
            Doc(id=2, name="b-1", tenant_id=TENANT_B),
        ]
    )
    session.commit()
    token = bind_tenant(TenantContext(tenant_id=TENANT_A))
    try:
        yield session
    finally:
        unbind_tenant(token)
        session.close()


# ── (2) fail-closed: raw SQL без tenant-контекста ────────────────────────


def test_raw_sql_without_tenant_context_is_rejected() -> None:
    """Без tenant-контекста raw SQL по tenant-таблице отклоняется.

    Раньше guard пропускал запрос целиком (``if tenant_id:``) — запрос
    возвращал строки всех tenant'ов (кросс-tenant чтение).
    """
    engine = _engine_with_workflow_instances()
    tf.apply_tenant_filter()
    session = Session(engine)

    with pytest.raises(tf.TenantIsolationError):
        session.execute(text("SELECT id, tenant_id FROM workflow_instances"))

    session.close()


def test_raw_sql_without_tenant_context_reports_missing_scope() -> None:
    """Отказ понятен: в тексте ошибки сказано про tenant-скоуп."""

    engine = _engine_with_workflow_instances()
    tf.apply_tenant_filter()
    session = Session(engine)

    with pytest.raises(tf.TenantIsolationError) as exc_info:
        session.execute(text("SELECT id, tenant_id FROM workflow_instances"))

    assert "tenant" in str(exc_info.value).lower()
    session.close()


def test_raw_sql_on_non_tenant_table_without_tenant_is_allowed() -> None:
    """Таблица без ``tenant_id`` не блокируется (нет риска утечки)."""
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE adr0417_plain (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO adr0417_plain (id) VALUES (1)"))
    tf.apply_tenant_filter()
    session = Session(engine)

    rows = session.execute(text("SELECT id FROM adr0417_plain")).all()

    assert [tuple(row) for row in rows] == [(1,)]
    session.close()


def test_orm_query_without_tenant_context_is_not_blocked() -> None:
    """ORM-путь без tenant'а не блокируется (фоновые/служебные пути)."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tf.apply_tenant_filter()
    session = Session(engine)
    session.add(Doc(id=1, name="a-1", tenant_id=TENANT_A))
    session.commit()
    set_tenant(TenantContext(tenant_id=""))

    ids = {row.id for row in session.execute(select(Doc)).scalars()}

    assert ids == {1}
    session.close()


# ── (1) внешний контур: guard не применяется ─────────────────────────────


def test_external_session_is_not_guarded() -> None:
    """Внешняя сессия: raw SQL по tenant-имени таблицы выполняется.

    Внешний контур — другая СУБД со своей схемой; tenant-guard к нему не
    применяется (иначе ``db_query_external`` / ``jdbc_query`` / ``batch_*``
    падают на любой таблице с tenant-именем).
    """
    engine = _engine_with_workflow_instances()
    tf.register_external_engine(engine)
    tf.apply_tenant_filter()
    session = Session(engine)
    token = bind_tenant(TenantContext(tenant_id=TENANT_A))
    try:
        rows = session.execute(
            text("SELECT id, tenant_id FROM workflow_instances")
        ).all()
    finally:
        unbind_tenant(token)
        session.close()

    assert rows == []


def test_external_session_returns_rows() -> None:
    """Внешняя сессия возвращает данные — guard не блокирует запрос."""
    engine = _engine_with_workflow_instances()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO workflow_instances (id, tenant_id, name) "
                "VALUES (1, 'tenant-a', 'a'), (2, 'tenant-b', 'b')"
            )
        )
    tf.register_external_engine(engine)
    tf.apply_tenant_filter()
    session = Session(engine)
    token = bind_tenant(TenantContext(tenant_id=TENANT_A))
    try:
        rows = session.execute(
            text("SELECT id, tenant_id FROM workflow_instances")
        ).all()
    finally:
        unbind_tenant(token)
        session.close()

    assert [tuple(row) for row in rows] == [(1, "tenant-a"), (2, "tenant-b")]


def test_main_session_still_guarded_for_same_table() -> None:
    """Тот же запрос в main-контуре по-прежнему отклоняется (контроль)."""
    engine = _engine_with_workflow_instances()
    tf.apply_tenant_filter()
    session = Session(engine)
    token = bind_tenant(TenantContext(tenant_id=TENANT_A))
    try:
        with pytest.raises(tf.TenantIsolationError):
            session.execute(text("SELECT id, tenant_id FROM workflow_instances"))
    finally:
        unbind_tenant(token)
        session.close()


def test_unknown_engine_is_treated_as_main() -> None:
    """Неизвестный движок → main-контур (fail-closed по умолчанию).

    Изоляция важнее доступности: движок, который не объявлен внешним,
    считается main'ом — guard применяется.
    """
    engine = _engine_with_workflow_instances()
    tf.apply_tenant_filter()
    session = Session(engine)
    token = bind_tenant(TenantContext(tenant_id=TENANT_A))
    try:
        with pytest.raises(tf.TenantIsolationError):
            session.execute(text("SELECT id, tenant_id FROM workflow_instances"))
    finally:
        unbind_tenant(token)
        session.close()


def test_external_engine_registration_is_idempotent() -> None:
    """Повторная регистрация внешнего движка — no-op."""
    engine = _engine_with_workflow_instances()

    tf.register_external_engine(engine)
    tf.register_external_engine(engine)

    assert tf.is_main_scope(Session(engine)) is False


def test_external_session_manager_registers_engine_as_external() -> None:
    """``DatabaseSessionManager`` внешнего профиля исключается из guard'а.

    Проверяет production-wiring: внешний sessionmaker создаётся через
    ``DatabaseSessionManager`` — его движок объявляется внешним, и raw SQL
    по tenant-имени таблицы проходит.
    """
    from sqlalchemy.orm import sessionmaker

    from src.backend.infrastructure.database.session_manager import (
        DatabaseSessionManager,
    )

    engine = _engine_with_workflow_instances()
    DatabaseSessionManager(
        session_maker=sessionmaker(bind=engine), db_name="external-profile"
    )

    session = Session(engine)
    try:
        assert tf.is_main_scope(session) is False
    finally:
        session.close()


def test_main_session_manager_keeps_guard_enabled() -> None:
    """Менеджер main-БД guard не отключает (изоляция сохраняется)."""
    from sqlalchemy.orm import sessionmaker

    from src.backend.infrastructure.database.session_manager import (
        DatabaseSessionManager,
    )

    engine = _engine_with_workflow_instances()
    DatabaseSessionManager(session_maker=sessionmaker(bind=engine), db_name="main")

    session = Session(engine)
    try:
        assert tf.is_main_scope(session) is True
    finally:
        session.close()


# ── (3) канонический список tenant-таблиц ────────────────────────────────


@pytest.mark.parametrize("table", ["orders", "users", "files", "orderkinds"])
def test_extension_tables_are_tenant_aware(table: str) -> None:
    """Extension-таблицы входят в ``tenant_aware_tables()``.

    ORM-моделей в ядре у них нет (модели — в ``extensions/``, грузятся
    лениво), поэтому без явного списка raw-SQL guard их не покрывал.
    """
    assert table in tf.tenant_aware_tables()


def test_canonical_list_is_subset_of_tenant_aware_tables() -> None:
    """Канонический список целиком входит в ``tenant_aware_tables()``."""
    assert TENANT_TABLES <= tf.tenant_aware_tables()


def test_canonical_list_matches_migrations() -> None:
    """Список совпадает с tenant-таблицами из миграций (без RLS-исключений).

    Канонический источник имён — миграции; расхождение с ними означает,
    что новая tenant-таблица не попала ни в guard, ни в RLS.
    """
    from importlib import import_module

    migration = import_module(
        "src.backend.infrastructure.database.migrations.versions."
        "2026_10_29_1200-e2f3a4b5c6d7_rls_all_tenant_tables"
    )

    assert {table.name for table in migration.RLS_TABLES} == set(TENANT_TABLES)


# ── регрессии ────────────────────────────────────────────────────────────


def test_orm_filter_still_applies(main_session: Session) -> None:
    """ORM-фильтр по tenant продолжает работать (инвариант)."""
    assert {row.id for row in main_session.execute(select(Doc)).scalars()} == {1}


def test_raw_sql_with_own_tenant_predicate_is_allowed(main_session: Session) -> None:
    """Явный tenant-предикат — запрос разрешён."""
    rows = main_session.execute(
        text("SELECT id, tenant_id FROM adr0417_docs WHERE tenant_id = :tenant_id"),
        {"tenant_id": TENANT_A},
    ).all()

    assert [tuple(row) for row in rows] == [(1, TENANT_A)]
