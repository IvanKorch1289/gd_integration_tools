from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gd_advanced_tools.models.base import BaseModel, nullable_str


__all__ = ('OrderKind',)


class OrderKind(BaseModel):
    """ORM-класс таблицы учета видов запросов."""

    __tableargs__ = {'сomment': 'Виды запросов в СКБ-Техно'}

    name: Mapped[nullable_str]
    description: Mapped[str] = mapped_column(Text, nullable=True)
    skb_uuid: Mapped[str] = mapped_column(String, unique=True, index=True)
    orders = relationship(
        'Order',
        back_populates='order_kind',
        cascade='save-update, merge, delete'
    )
