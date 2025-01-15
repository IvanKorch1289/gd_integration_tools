from datetime import datetime

from backend.base.schemas import PublicSchema


__all__ = (
    "OrderKindSchemaIn",
    "OrderKindSchemaOut",
)


class OrderKindSchemaIn(PublicSchema):
    """
    Схема для входящих данных вида запроса.

    Атрибуты:
        name (str | None): Название вида запроса. По умолчанию None.
        description (str | None): Описание вида запроса. По умолчанию None.
        skb_uuid (str | None): Уникальный идентификатор SKB. По умолчанию None.
    """

    name: str = None
    description: str | None = None
    skb_uuid: str = None


class OrderKindSchemaOut(OrderKindSchemaIn):
    """
    Схема для исходящих данных вида запроса.

    Наследует атрибуты из OrderKindSchemaIn и добавляет дополнительные поля.

    Атрибуты:
        id (int): Уникальный идентификатор вида запроса.
        created_at (datetime): Время создания записи.
        updated_at (datetime): Время последнего обновления записи.
    """

    id: int
    created_at: datetime
    updated_at: datetime
