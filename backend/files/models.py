from sqlalchemy import UUID, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.base.models import BaseModel


__all__ = (
    "File",
    "OrderFile",
)


class File(BaseModel):
    """ORM-класс таблицы учета файлов."""

    __table_args__ = {"comment": "Данные файлов"}

    name: Mapped[str] = mapped_column(String, nullable=True)
    object_uuid: Mapped[UUID] = mapped_column(
        UUID, nullable=False, server_default=func.gen_random_uuid(), index=True
    )
    orders = relationship(
        "Order", secondary=lambda: OrderFile.__table__, back_populates="files"
    )


class OrderFile(BaseModel):
    """Промежуточная таблица для связи Order и File."""

    __table_args__ = {"comment": "Связь заказов и файлов"}

    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id"), primary_key=True
    )
    file_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("files.id"), primary_key=True
    )
