from sqlalchemy import UUID, Boolean, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    order_kind = relationship('OrderKind', back_populates='orders')
    pledge_gd_id: Mapped[int] = mapped_column(Integer, nullable=False)
    pledge_cadastral_number: Mapped[nullable_str]
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default='t',
    )
    is_send_to_gd: Mapped[bool] = mapped_column(
        Boolean,
        server_default='f',
    )
    errors: Mapped[str] = mapped_column(Text, nullable=True)
    object_uuid: Mapped[UUID] = mapped_column(
        UUID,
        nullable=False,
        server_default=func.gen_random_uuid(),
    )
