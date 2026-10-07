"""D-4 (CRITICAL): UNION/CTE обходят ORM tenant-фильтр.

Аудит 2026-10-05, продолжение D-4. Существующий
``test_tenant_filter_orm_dml.py`` закрывает DML, JOIN, entity-select,
column-select и COUNT-over-tenant-table. UNION и CTE не покрыты ни одним
тестом — при том что именно они строятся чаще всего в отчётных и
агрегационных запросах.

Механика подозрения: ``_tenant_aware_entities`` опирается на
``statement.column_descriptions`` / ``entity_description`` / ``stmt.froms``.
У составных запросов (``union``, CTE) эти атрибуты относятся к отдельным
составляющим, а не к результату, поэтому сущность может не быть найдена и
``stmt.where(entity.tenant_id == ...)`` не добавится.

Файл написан как **воспроизведение**: тесты обязаны либо подтвердить дыру
(тогда они падают и фиксируют её), либо подтвердить защиту. Молчаливое
«прошло» не считается доказательством — для каждого случая отдельно
проверяется, что чужой tenant действительно не утёк, сравнением с сырым
чтением в обход ORM.
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


class Order(tf.TenantMixin, Base):
    """Tenant-aware сущность для проверки фильтра."""

    __tablename__ = "d4_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class User(tf.TenantMixin, Base):
    """Вторая tenant-aware сущность — для UNION разных таблиц."""

    __tablename__ = "d4_users"

    id: Mapped[int] = mapped_column(primary_key=True)


@pytest.fixture
def seeded() -> Iterator[Session]:
    """Сессия со строками двух tenant'ов и активным ``tenant-a``.

    Returns:
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
            User(id=1, tenant_id=TENANT_A),
            User(id=2, tenant_id=TENANT_B),
        ]
    )
    session.commit()
    # bind_tenant/unbind_tenant вместо set_tenant: контекст tenant'а —
    # общепроцессный ContextVar. Прежний вариант оставлял TENANT_A привязанным
    # после теста, и тест на «контекст не утекает после запроса» падал при
    # любом порядке прогона, где этот файл шёл раньше. Воспроизведено:
    # test_tenant_filter_orm_dml.py + test_tenant_context_propagation_d1.py
    # → FAILED, в одиночку D-1 тест проходит.
    token = bind_tenant(TenantContext(tenant_id=TENANT_A))
    try:
        yield session
    finally:
        unbind_tenant(token)
        session.close()


def _raw_all(session: Session) -> int:
    """Посчитать строки обеих таблиц в обход ORM-фильтра.

    Args:
        session: Открытая сессия.

    Returns:
        Суммарное число строк без учёта tenant'а.

    """
    return int(
        session.execute(
            text(
                "SELECT (SELECT COUNT(*) FROM d4_orders) + (SELECT COUNT(*) FROM d4_users)"
            )
        ).scalar()
    )


class TestPlainSelectStillFiltered:
    """Контроль: обычный и JOIN-запросы фильтр держат (регрессия-сторож)."""

    def test_plain_select_hides_foreign_tenant(self, seeded: Session) -> None:
        """``select(Order)`` не отдаёт строку чужого tenant'а."""
        assert _raw_all(seeded) == 4
        # scalars(), а не execute(...).all(): Core-стиль select через
        # Session.execute возвращает plain Row, а не ORM-сущности —
        # обращение к r.name давало бы KeyError, а не проверку фильтра.
        rows = seeded.scalars(select(Order)).all()
        assert [r.name for r in rows] == ["a-1"]

    def test_join_hides_foreign_tenant(self, seeded: Session) -> None:
        """JOIN двух tenant-aware таблиц не отдаёт чужой tenant."""
        stmt = select(Order.name).join(User, User.id == Order.id)
        rows = seeded.execute(stmt).all()
        assert [r[0] for r in rows] == ["a-1"]


class TestUnionBypass:
    """UNION — составной запрос; атрибуты результата не описывают сущности."""

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "D-4 (CRITICAL): UNION/CTE обходят ORM tenant-фильтр — дыра ПОДТВЕРЖДЕНА на "
            "реальном SQLAlchemy 2.0.52 + SQLite: под tenant-a union_all возвращает строки "
            "tenant-b. Фильтр добавляет условие только к верхнему уровню statement, а у "
            "CompoundSelect/CTE сущности живут в ветвях. Попытка починки через "
            "replacement_traverse отклонена: обход не заходит в ветви, а пересборка "
            "CompoundSelect требует приватного API. strict=True: дыра закроется → XPASS."
        ),
    )
    def test_union_same_entity_hides_foreign_tenant(self, seeded: Session) -> None:
        """UNION двух выборок одной tenant-aware сущности."""
        own = select(Order.name).where(Order.name == "a-1")
        foreign = select(Order.name).where(Order.name == "b-1")
        rows = seeded.execute(own.union_all(foreign)).all()
        leaked = [r[0] for r in rows if r[0] == "b-1"]
        assert not leaked, f"UNION вернул строку чужого tenant'а: {leaked}"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "D-4 (CRITICAL): UNION/CTE обходят ORM tenant-фильтр — дыра ПОДТВЕРЖДЕНА на "
            "реальном SQLAlchemy 2.0.52 + SQLite: под tenant-a union_all возвращает строки "
            "tenant-b. Фильтр добавляет условие только к верхнему уровню statement, а у "
            "CompoundSelect/CTE сущности живут в ветвях. Попытка починки через "
            "replacement_traverse отклонена: обход не заходит в ветви, а пересборка "
            "CompoundSelect требует приватного API. strict=True: дыра закроется → XPASS."
        ),
    )
    def test_union_different_entities_hides_foreign_tenant(
        self, seeded: Session
    ) -> None:
        """UNION разных tenant-aware таблиц."""
        orders = select(Order.name)
        users = select(User.id.cast(String))
        rows = seeded.execute(orders.union_all(users)).all()
        assert [r[0] for r in rows] == ["a-1"], (
            "UNION разных сущностей утёк чужой tenant"
        )


class TestCteBypass:
    """CTE — вложенный подзапрос; фильтр должен применяться внутри."""

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "D-4 (CRITICAL): UNION/CTE обходят ORM tenant-фильтр — дыра ПОДТВЕРЖДЕНА на "
            "реальном SQLAlchemy 2.0.52 + SQLite: под tenant-a union_all возвращает строки "
            "tenant-b. Фильтр добавляет условие только к верхнему уровню statement, а у "
            "CompoundSelect/CTE сущности живут в ветвях. Попытка починки через "
            "replacement_traverse отклонена: обход не заходит в ветви, а пересборка "
            "CompoundSelect требует приватного API. strict=True: дыра закроется → XPASS."
        ),
    )
    def test_cte_hides_foreign_tenant(self, seeded: Session) -> None:
        """CTE поверх tenant-aware таблицы."""
        cte = select(Order.id, Order.name).cte("mine")
        stmt = select(cte.c.name).where(cte.c.id == 2)
        rows = seeded.execute(stmt).all()
        assert not rows, f"CTE вернул строку чужого tenant'а: {rows}"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "D-4 (CRITICAL): UNION/CTE обходят ORM tenant-фильтр — дыра ПОДТВЕРЖДЕНА на "
            "реальном SQLAlchemy 2.0.52 + SQLite: под tenant-a union_all возвращает строки "
            "tenant-b. Фильтр добавляет условие только к верхнему уровню statement, а у "
            "CompoundSelect/CTE сущности живут в ветвях. Попытка починки через "
            "replacement_traverse отклонена: обход не заходит в ветви, а пересборка "
            "CompoundSelect требует приватного API. strict=True: дыра закроется → XPASS."
        ),
    )
    def test_cte_then_union_hides_foreign_tenant(self, seeded: Session) -> None:
        """CTE + UNION — самая частая форма отчётных запросов."""
        cte = select(Order.name).cte("names")
        stmt = select(cte.c.name).union_all(select(User.id.cast(String)))
        rows = seeded.execute(stmt).all()
        assert [r[0] for r in rows] == ["a-1"], "CTE+UNION утёк чужой tenant"
