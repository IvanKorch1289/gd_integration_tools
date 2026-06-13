from sqlalchemy import UUID, Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy_utils.types import EmailType, UUIDType

from src.backend.core.domain.models.base import BaseModel, nullable_str
from .files import OrderFile
from src.backend.infrastructure.database.tenant_filter import TenantMixin

__all__ = ("Order",)


class Order(BaseModel, TenantMixin):
    """
    ORM-класс таблицы учета запросов.

    Атрибуты:
        order_kind_id (int): Идентификатор вида запроса.
        pledge_gd_id (int): Идентификатор залога в ГД.
        pledge_cadastral_number (str | None): Кадастровый номер залога.
        is_active (bool): Флаг активности запроса.
        is_send_to_gd (bool): Флаг отправки запроса в ГД.
        is_send_request_to_skb (bool): Флаг отправки запроса в СКБ.
        errors (str | None): Ошибки, связанные с запросом.
        object_uuid (UUID): Уникальный идентификатор объекта.
        response_data (JSON): Данные ответа.
        email_for_answer (str): Email для ответа.
        order_kind (OrderKind): Связь с видом запроса.
        files (list[File]): Связь с файлами, прикрепленными к запросу.
        tenant_id (str): Tenant identifier для multi-tenancy (S89 W2+W3, V2 P0 #6).

    History:
        * S89 W2 (V2 P0 #6): tenant_id column added via Alembic migration
          d6e7f8a9b0c1 (2026-06-12 19:00). NOT NULL DEFAULT 'default' для
          backward-compat з existing rows. Index ix_orders_tenant_id для
          apply_tenant_filter performance.
        * S89 W3 (V2 P0 #6): додано TenantMixin в MRO для auto-filter.
          apply_tenant_filter (S88 W2) тепер буде фільтрувати Order queries
          по tenant_id коли встановлено в contextvar.
    """

    __table_args__ = {"comment": "Запросы в СКБ-Техно"}

    # Поля таблицы
    order_kind_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orderkinds.id"), nullable=False
    )
    pledge_gd_id: Mapped[int] = mapped_column(Integer, nullable=False)
    pledge_cadastral_number: Mapped[nullable_str]
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="t")
    is_send_to_gd: Mapped[bool] = mapped_column(Boolean, server_default="f")
    is_send_request_to_skb: Mapped[bool] = mapped_column(Boolean, server_default="f")
    errors: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_uuid: Mapped[UUID] = mapped_column(
        UUIDType, nullable=False, server_default=func.gen_random_uuid()
    )
    response_data: Mapped[JSON] = mapped_column(JSON, nullable=True)
    email_for_answer: Mapped[str] = mapped_column(EmailType, nullable=False)

    # Связи
    order_kind = relationship("OrderKind", back_populates="orders", lazy="joined")
    files = relationship(
        "File", secondary=OrderFile.__table__, back_populates="orders", lazy="joined"
    )

    # Исключаемые связи (например, "versions")
    EXCLUDED_RELATIONSHIPS = {"versions"}
