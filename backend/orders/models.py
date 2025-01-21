from sqlalchemy import UUID, Boolean, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy_utils.types import EmailType, UUIDType

from backend.base.models import BaseModel, nullable_str
from backend.files.models import OrderFile


__all__ = ("Order",)


class Order(BaseModel):
    """ORM-класс таблицы учета запросов."""

    __table_args__ = {"comment": "Запросы в СКБ-Техно"}
    __versioned__ = {}

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
    is_send_request_to_skb: Mapped[bool] = mapped_column(
        Boolean,
        server_default="f",
    )
    errors: Mapped[str] = mapped_column(Text, nullable=True)
    object_uuid: Mapped[UUID] = mapped_column(
        UUIDType,
        nullable=False,
        server_default=func.gen_random_uuid(),
    )
    response_data: Mapped[JSON] = mapped_column(JSON, nullable=True)
    email_for_answer: Mapped[str] = mapped_column(EmailType, nullable=False)

    # Relationships
    order_kind = relationship("OrderKind", back_populates="orders", lazy="joined")
    files = relationship(
        "File",
        secondary=lambda: OrderFile.__table__,
        back_populates="orders",
        lazy="joined",
    )
