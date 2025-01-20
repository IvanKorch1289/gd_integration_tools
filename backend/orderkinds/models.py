from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.base.models import BaseModel, nullable_str


__all__ = ("OrderKind",)


class OrderKind(BaseModel):
    """
    ORM-класс таблицы учета видов запросов.

    Атрибуты:
        name (Mapped[nullable_str]): Название вида запроса.
        description (Mapped[str]): Описание вида запроса. Может быть пустым.
        skb_uuid (Mapped[str]): Уникальный идентификатор SKB. Индексируется для быстрого поиска.

    Таблица:
        __table_args__: Комментарий к таблице - "Виды запросов в СКБ-Техно".

    Связи:
        orders (relationship): Связь с таблицей заказов (Order). Каскадные операции: save-update, merge, delete.
    """

    __table_args__ = {"comment": "Виды запросов в СКБ-Техно"}

    name: Mapped[nullable_str]
    description: Mapped[str] = mapped_column(Text, nullable=True)
    skb_uuid: Mapped[str] = mapped_column(String, unique=True, index=True)

    # Relationships
    orders = relationship(
        "Order", back_populates="order_kind", cascade="save-update, merge, delete"
    )
