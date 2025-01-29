from datetime import datetime

from app.schemas import BaseSchema


__all__ = (
    "OrderKindSchemaIn",
    "OrderKindSchemaOut",
    "OrderKindVersionSchemaOut",
)


class OrderKindSchemaIn(BaseSchema):
    """
    Схема для входящих данных вида запроса.

    Атрибуты:
        name (str | None): Название вида запроса. По умолчанию None.
        description (str | None): Описание вида запроса. По умолчанию None.
        skb_uuid (str | None): Уникальный идентификатор SKB. По умолчанию None.
    """

    name: str | None = None
    description: str | None = None
    skb_uuid: str | None = None


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


class OrderKindVersionSchemaOut(OrderKindSchemaOut):
    """
    Схема для исходящих данных версии вида запроса.

    Наследует атрибуты из OrderKindSchemaOut и добавляет дополнительные поля.

    Атрибуты:
        operation_type (int): Тип операции (создание, обновление, удаление).
        transaction_id (int): Идентификатор транзакции.
    """

    operation_type: int
    transaction_id: int
