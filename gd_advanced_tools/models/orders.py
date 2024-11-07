from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from gd_advanced_tools.models.base import BaseModel, nullable_str


__all__ = ('Order',)


class Order(BaseModel):
    """ORM-класс таблицы учета запросов."""

    __tableargs__ = {'сomment': 'Запросы в СКБ-Техно'}

    order_kind_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey('orderkinds.id'),
        nullable=False
    )
    pledge_gd_id: Mapped[int] = mapped_column(Integer, nullable=False)
    pledge_cadastral_number: Mapped[nullable_str]
