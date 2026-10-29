"""Wave 16 / X4: raw SQL не должен обходить tenant-изоляцию (ADR-0383).

До правки ORM-фильтр применялся только к ORM-состояниям
(``do_orm_execute`` → ``is_select/is_update/is_delete``). Для
``text(...)`` SQLAlchemy выставляет **все три флага в False**, поэтому
``text("SELECT * FROM docs")`` проходил без фильтра и возвращал строки
чужих tenant'ов (воспроизведено: 1 строка tenant-a + 1 строка tenant-b).

Контракт после правки — fail-closed: raw SQL по tenant-aware таблице
обязан содержать явный tenant-предикат (``tenant_id = :tenant_id`` с
значением текущего tenant'а). Всё остальное (таблицы без tenant_id,
операционные запросы вида ``SELECT 1``) не блокируется.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from src.backend.core.tenancy import TenantContext, bind_tenant, unbind_tenant
from src.backend.core.tenancy import sqlalchemy_filter as tf

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


class Base(DeclarativeBase):
    """Базовый declarative для изолированных тестовых моделей."""


class Doc(tf.TenantMixin, Base):
    """Tenant-aware сущность: её таблица защищена raw-SQL guard'ом."""

    __tablename__ = "x4_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(100))


class Plain(Base):
    """Таблица без ``tenant_id`` — raw SQL по ней остаётся разрешённым."""

    __tablename__ = "x4_plain"

    id: Mapped[int] = mapped_column(primary_key=True)


@pytest.fixture
def seeded() -> Iterator[Session]:
    """Сессия с двумя tenant-строками и активным ``tenant-a``.

    Returns:
        Открытая сессия; фильтр зарегистрирован глобально (идемпотентно).
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tf.apply_tenant_filter()
    session = Session(engine)
    session.add_all(
        [
            Doc(id=1, email="a@example.com", tenant_id=TENANT_A),
            Doc(id=2, email="b@example.com", tenant_id=TENANT_B),
            Plain(id=1),
        ]
    )
    session.commit()
    token = bind_tenant(TenantContext(tenant_id=TENANT_A))
    try:
        yield session
    finally:
        unbind_tenant(token)
        session.close()


def test_orm_select_returns_only_own_tenant(seeded: Session) -> None:
    """ORM-путь отдаёт только строку своего tenant'а (контроль).

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    assert {d.id for d in seeded.execute(select(Doc)).scalars()} == {1}


def test_raw_sql_without_tenant_predicate_is_blocked(seeded: Session) -> None:
    """Raw SQL без tenant-предиката обязан быть отвергнут (fail-closed).

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    with pytest.raises(tf.TenantIsolationError):
        seeded.execute(text("SELECT id, tenant_id FROM x4_docs"))


def test_raw_sql_does_not_leak_foreign_tenant(seeded: Session) -> None:
    """Даже после блокировки чужой tenant не должен попасть в результат.

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    leaked: list[object] = []
    try:
        rows = seeded.execute(text("SELECT id, tenant_id FROM x4_docs")).all()
        leaked = list(rows)
    except tf.TenantIsolationError:
        leaked = []

    assert leaked == [], f"raw SQL утёк строки чужого tenant'а: {leaked}"


def test_raw_sql_with_own_tenant_predicate_is_allowed(seeded: Session) -> None:
    """Явный предикат с tenant'ом текущего контекста — разрешён.

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    rows = seeded.execute(
        text("SELECT id, tenant_id FROM x4_docs WHERE tenant_id = :tenant_id"),
        {"tenant_id": TENANT_A},
    ).all()
    assert [tuple(row) for row in rows] == [(1, TENANT_A)]


def test_raw_sql_with_literal_tenant_is_allowed(seeded: Session) -> None:
    """Тот же контракт для литерального tenant_id (без bind-параметра).

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    rows = seeded.execute(
        text(f"SELECT id, tenant_id FROM x4_docs WHERE tenant_id = '{TENANT_A}'")
    ).all()
    assert [tuple(row) for row in rows] == [(1, TENANT_A)]


def test_raw_sql_with_foreign_tenant_param_is_blocked(seeded: Session) -> None:
    """Bind-параметр с чужим tenant'ом — тоже блокируется.

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    with pytest.raises(tf.TenantIsolationError):
        seeded.execute(
            text("SELECT id, tenant_id FROM x4_docs WHERE tenant_id = :tenant_id"),
            {"tenant_id": TENANT_B},
        )


def test_raw_sql_on_non_tenant_table_is_allowed(seeded: Session) -> None:
    """Таблица без ``tenant_id`` не блокируется (нет риска утечки).

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    rows = seeded.execute(text("SELECT id FROM x4_plain")).all()
    assert [tuple(row) for row in rows] == [(1,)]


def test_raw_sql_without_tenant_context_is_allowed(seeded: Session) -> None:
    """Без tenant в контексте guard не применяется (прежний контракт).

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    from src.backend.core.tenancy import set_tenant

    set_tenant(TenantContext(tenant_id=""))
    try:
        rows = seeded.execute(text("SELECT id, tenant_id FROM x4_docs")).all()
    finally:
        set_tenant(TenantContext(tenant_id=TENANT_A))
    assert len(rows) == 2
