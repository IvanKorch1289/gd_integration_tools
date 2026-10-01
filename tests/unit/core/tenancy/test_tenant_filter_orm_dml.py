"""F-AM: ORM-фильтр tenant действительно изолирует SELECT/JOIN/UPDATE/DELETE.

Аудит 2026-10-01. Прежний listener в
:mod:`src.backend.core.tenancy.sqlalchemy_filter` имел два дефекта, оба
воспроизведены на реальном SQLAlchemy 2.0.52 + SQLite (не на mock):

* **DML не фильтровался вообще** — ``if not orm_execute_state.is_select: return``
  отбрасывал ``UPDATE``/``DELETE``. ``repository.update()`` и
  ``repository.delete()`` меняли чужой tenant (rowcount=1 при чужом id);
* **JOIN-запросы не фильтровались** — сущность искалась через
  ``stmt.froms[i].entity_namespace``, а у ``_ORMJoin`` это коллекция колонок,
  а не класс, поэтому ``_is_tenant_aware()`` давал ``False`` и фильтр
  молча не добавлялся.

Уточнение к формулировке агента: обычный ``select(Entity)`` фильтровался
корректно (``froms[0]`` — ``Table``, чей namespace проксирует ``tenant_id``).
Утечка ограничивалась join-формами — это зафиксировано здесь, чтобы правка
не была принята за «select не фильтровался никогда».

Тесты на существующих ``MagicMock``-стейтах (``test_tenant_filter_e2e.py``)
такой дефект поймать не могут: mock не воспроизводит ни ``_ORMJoin``, ни DML —
это отдельный finding (F-AN, пустые тесты).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import String, create_engine, delete, func, select, text, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from src.backend.core.tenancy import TenantContext, set_tenant
from src.backend.core.tenancy import sqlalchemy_filter as tf

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


class Base(DeclarativeBase):
    """Базовый declarative для изолированных тестовых моделей."""


class Order(tf.TenantMixin, Base):
    """Tenant-aware сущность для проверки фильтра."""

    __tablename__ = "am_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class User(tf.TenantMixin, Base):
    """Вторая tenant-aware сущность — для проверки join из двух таблиц."""

    __tablename__ = "am_users"

    id: Mapped[int] = mapped_column(primary_key=True)


@pytest.fixture
def seeded() -> Session:
    """Сессия с двумя tenant-строками в каждой таблице.

    Returns:
        Открытая сессия; фильтр зарегистрирован глобально (идемпотентно).
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tf.apply_tenant_filter()
    session = Session(engine)
    session.add_all(
        [
            Order(id=1, name="a-1", tenant_id=TENANT_A),
            Order(id=2, name="b-1", tenant_id=TENANT_B),
            User(id=1, tenant_id=TENANT_A),
            User(id=2, tenant_id=TENANT_B),
        ]
    )
    session.commit()
    set_tenant(TenantContext(tenant_id=TENANT_A))
    return session


def _raw_orders(session: Session) -> list[tuple[object, ...]]:
    """Прочитать таблицу в обход ORM-фильтра.

    Args:
        session: Открытая сессия.

    Returns:
        Все строки ``orders`` как кортежи.
    """
    return [
        tuple(row)
        for row in session.execute(text("SELECT id, name, tenant_id FROM am_orders"))
    ]


# ── F-AM.1: DML ────────────────────────────────────────────────────────


def test_update_foreign_tenant_is_noop(seeded: Session) -> None:
    """UPDATE чужой tenant не должен затрагивать ни одной строки.

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    result = seeded.execute(update(Order).where(Order.id == 2).values(name="HIJACKED"))
    assert result.rowcount == 0
    seeded.commit()
    assert ("HIJACKED", TENANT_B) not in {
        (row[1], row[2]) for row in _raw_orders(seeded)
    }


def test_delete_foreign_tenant_is_noop(seeded: Session) -> None:
    """DELETE чужой tenant не должен удалять строку.

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    result = seeded.execute(delete(Order).where(Order.id == 2))
    assert result.rowcount == 0
    seeded.commit()
    assert (2, "b-1", TENANT_B) in _raw_orders(seeded)


def test_update_own_tenant_still_works(seeded: Session) -> None:
    """Собственный tenant остаётся редактируемым — изоляция не ломает работу.

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    result = seeded.execute(update(Order).where(Order.id == 1).values(name="mine"))
    assert result.rowcount == 1
    seeded.commit()
    assert (1, "mine", TENANT_A) in _raw_orders(seeded)


def test_delete_own_tenant_still_works(seeded: Session) -> None:
    """Собственный tenant остаётся удаляемым.

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    result = seeded.execute(delete(Order).where(Order.id == 1))
    assert result.rowcount == 1
    seeded.commit()
    assert (1, "mine", TENANT_A) not in _raw_orders(seeded)
    assert (2, "b-1", TENANT_B) in _raw_orders(seeded)


# ── F-AM.2: JOIN ───────────────────────────────────────────────────────


def test_join_query_is_filtered(seeded: Session) -> None:
    """Join двух tenant-aware таблиц не должен возвращать чужой tenant.

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    rows = seeded.execute(select(Order, User.id).join(User, User.id == Order.id)).all()
    assert {row[0].id for row in rows} == {1}


# ── Инварианты, которые не должны сломаться ───────────────────────────


def test_entity_select_still_filtered(seeded: Session) -> None:
    """Базовый ``select(Entity)`` продолжает фильтроваться.

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    assert {o.id for o in seeded.execute(select(Order)).scalars()} == {1}


def test_column_select_still_filtered(seeded: Session) -> None:
    """``select(Entity.column)`` продолжает фильтроваться.

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    assert set(seeded.execute(select(Order.id)).scalars()) == {1}


def test_count_over_tenant_table_is_filtered(seeded: Session) -> None:
    """Агрегат без column-описаний (``select_from``) не обходит фильтр.

    Args:
        seeded: Сессия с активным ``tenant-a``.
    """
    assert seeded.execute(select(func.count()).select_from(Order)).scalar() == 1


def test_no_tenant_context_does_not_filter(seeded: Session) -> None:
    """Без tenant в контексте фильтр не применяется (совпадает с контрактом).

    Fail-closed на уровне потребителей (см. F-07/F-11), а не здесь: без
    tenant система не знает, что фильтровать.

    Args:
        seeded: Сессия.
    """
    set_tenant(TenantContext(tenant_id=""))
    assert len(seeded.execute(select(Order)).scalars().all()) == 2
    set_tenant(TenantContext(tenant_id=TENANT_A))


def test_non_tenant_entity_not_filtered(tmp_path: Path) -> None:
    """Сущность без ``tenant_id`` не фильтруется — mixin не навязан.

    Args:
        tmp_path: Не используется; нужен для сигнатуры фикстуры.
    """

    class Plain(Base):
        """Сущность без TenantMixin."""

        __tablename__ = "am_plain"

        id: Mapped[int] = mapped_column(primary_key=True)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tf.apply_tenant_filter()
    with Session(engine) as session:
        session.add_all([Plain(id=1), Plain(id=2)])
        session.commit()
        set_tenant(TenantContext(tenant_id=TENANT_A))
        assert len(session.execute(select(Plain)).scalars().all()) == 2
        set_tenant(TenantContext(tenant_id=TENANT_A))
