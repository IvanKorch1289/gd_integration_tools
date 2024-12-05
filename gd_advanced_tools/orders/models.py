from sqlalchemy import UUID, Boolean, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gd_advanced_tools.base.models import BaseModel, nullable_str
from gd_advanced_tools.files.models import OrderFile


__all__ = ("Order",)


class Order(BaseModel):
    """ORM-класс таблицы учета запросов."""

    __table_args__ = {"comment": "Запросы в СКБ-Техно"}

    order_kind_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orderkinds.id"), nullable=False
    )
    pledge_gd_id: Mapped[int] = mapped_column(Integer, nullable=False)
    pledge_cadastral_number: Mapped[nullable_str]
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        server_default="t",
    )
    is_send_to_gd: Mapped[bool] = mapped_column(
        Boolean,
        server_default="f",
    )
    errors: Mapped[str] = mapped_column(Text, nullable=True)
    object_uuid: Mapped[UUID] = mapped_column(
        UUID,
        nullable=False,
        server_default=func.gen_random_uuid(),
    )
    response_data: Mapped[JSON] = mapped_column(JSON, nullable=True)
    order_kind = relationship("OrderKind", back_populates="orders")
    files = relationship(
        "File", secondary=lambda: OrderFile.__table__, back_populates="orders"
    )
