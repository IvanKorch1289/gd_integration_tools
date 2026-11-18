"""CTE + ORM tenant-фильтр: cartesian product во внешнем запросе.

Регрессия (аудит волны 34, зона core/tenancy): ``_filter_statement``
добавлял tenant-предикат и по сущностям **внутри** CTE-определения, хотя
они уже отфильтрованы в самом определении. Внешний запрос получал лишний
``FROM`` и предикат::

    WITH c AS (SELECT ... WHERE tenant_id = :t)
    SELECT c.id FROM c, orders WHERE orders.tenant_id = :t   -- cartesian product

Итог — дублированные строки (``2 строки tenant-a → 4 строки``) и
предупреждение SQLAlchemy о cartesian product. Утечки чужого tenant'а
не было (предикат оставался), но данные возвращались неверными.

Существующий ``test_tenant_filter_union_cte_d4.py`` проверял только
отсутствие утечки, а не количество строк — дефект проходил незамеченным.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from src.backend.core.tenancy import TenantContext, bind_tenant, unbind_tenant
from src.backend.core.tenancy import sqlalchemy_filter as tf

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"

pytestmark = pytest.mark.unit


class Base(DeclarativeBase):
    """Базовый declarative для изолированных тестовых моделей."""


class Order(tf.TenantMixin, Base):
    """Tenant-aware сущность для проверки фильтра."""

    __tablename__ = "cte_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


@pytest.fixture
def seeded() -> Iterator[Session]:
    """Сессия со строками двух tenant'ов и активным ``tenant-a``.

    Yields:
        Открытая сессия с включённым ORM-фильтром.

    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tf.apply_tenant_filter()
    session = Session(engine)
    session.add_all(
        [
            Order(id=1, name="a-1", tenant_id=TENANT_A),
            Order(id=2, name="b-1", tenant_id=TENANT_B),
            Order(id=3, name="a-2", tenant_id=TENANT_A),
        ]
    )
    session.commit()
    token = bind_tenant(TenantContext(tenant_id=TENANT_A))
    try:
        yield session
    finally:
        unbind_tenant(token)
        session.close()


class TestCteNoCartesianProduct:
    """CTE не должен размножать строки внешнего запроса."""

    def test_cte_returns_each_row_once(self, seeded: Session) -> None:
        """CTE поверх tenant-aware таблицы: ровно одна строка на строку tenant'а."""
        cte = select(Order.id, Order.name).cte("mine")

        rows = seeded.execute(select(cte.c.name)).all()

        assert [r[0] for r in rows] == ["a-1", "a-2"]

    def test_cte_with_where_returns_each_row_once(self, seeded: Session) -> None:
        """CTE с дополнительным условием — количество строк не меняется."""
        cte = select(Order.id, Order.name).where(Order.name != "zzz").cte("mine")

        rows = seeded.execute(select(cte.c.name)).all()

        assert [r[0] for r in rows] == ["a-1", "a-2"]

    def test_cte_joined_with_tenant_table(self, seeded: Session) -> None:
        """CTE + прямая tenant-aware сущность: обе отфильтрованы, дублей нет."""
        cte = select(Order.id, Order.name).cte("mine")

        stmt = (
            select(cte.c.name, Order.id)
            .select_from(cte)
            .join(Order, Order.id == cte.c.id)
        )
        rows = seeded.execute(stmt).all()

        assert sorted(r[0] for r in rows) == ["a-1", "a-2"]
        assert all(r[1] is not None for r in rows)
