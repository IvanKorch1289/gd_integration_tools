from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gd_advanced_tools.models.base import Base
from gd_advanced_tools.models.orders import Order


__all__ = ('OrderKind',)


class OrderKind(Base):
    """ORM-класс таблицы учета видов запросов."""

    __tableargs__ = {'сomment': 'Виды запросов в СКБ-Техно'}

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    skb_uuid: Mapped[str] = mapped_column(String, unique=True, index=True)
    orders: Mapped[list['Order']] = relationship(
        'Order',
        back_populates='order_kind',
        cascade='save-update, merge, delete'
    )
