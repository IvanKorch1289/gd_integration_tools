from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from gd_advanced_tools.models.base import Base


__all__ = ('Order',)


class Order(Base):
    """ORM-класс таблицы учета запросов."""

    __tableargs__ = {'сomment': 'Запросы в СКБ-Техно'}

    order_kind_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey('orderkinds.id'),
        nullable=False
    )
    pledge_gd_id: Mapped[int] = mapped_column(Integer, nullable=False)
