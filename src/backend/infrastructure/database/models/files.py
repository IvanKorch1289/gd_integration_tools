from sqlalchemy import UUID, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.backend.core.domain.models.base import Base, BaseModel
from src.backend.infrastructure.database.tenant_filter import TenantMixin

__all__ = ("File", "OrderFile")


class File(BaseModel, TenantMixin):
    """
    ORM-класс таблицы учета файлов.

    S92 W2 (V2 P0 #6 continue): тепер TenantMixin subclass.
    3/7 моделей tenant-isolated (Order + User + File).

    Атрибуты:
        name (Mapped[str]): Название файла. Может быть пустым.
        object_uuid (Mapped[UUID]): Уникальный идентификатор объекта, связанного с файлом.
                                   По умолчанию генерируется случайный UUID.
        orders (relationship): Связь с таблицей заказов через промежуточную таблицу OrderFile.

    Таблица:
        __table_args__: Комментарий к таблице - "Данные файлов".
    """

    __table_args__ = {"comment": "Данные файлов"}

    name: Mapped[str] = mapped_column(String, nullable=True)
    object_uuid: Mapped[UUID] = mapped_column(
        UUID, nullable=False, server_default=func.gen_random_uuid(), index=True
    )

    # Relationships
    orders = relationship(
        "Order", secondary=lambda: OrderFile.__table__, back_populates="files"
    )


class OrderFile(Base):
    """
    Промежуточная таблица для связи заказов (Order) и файлов (File).

    Атрибуты:
        order_id (Mapped[int]): Внешний ключ, ссылающийся на таблицу заказов (orders.id).
        file_id (Mapped[int]): Внешний ключ, ссылающийся на таблицу файлов (files.id).

    Таблица:
        __table_args__: Комментарий к таблице - "Связь заказов и файлов".
    """

    __tablename__ = "orderfiles"
    __table_args__ = (
        UniqueConstraint("order_id", "file_id", name="uq_order_file"),
        {"comment": "Связь заказов и файлов"},
    )

    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id"), primary_key=True
    )
    file_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("files.id"), primary_key=True
    )
