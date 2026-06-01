from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from src.backend.schemas.base import BaseSchema
from src.backend.schemas.route_schemas.files import FileSchemaOut
from src.backend.schemas.route_schemas.orderkinds import OrderKindSchemaOut

__all__ = (
    "OrderSchemaIn",
    "OrderSchemaOut",
    "OrderVersionSchemaOut",
    "OrderIdQuerySchema",
    "OrderIdPathSchema",
)


class OrderSchemaIn(BaseSchema):
    """
    Схема для входящих данных заказа.

    Attributes:
        pledge_gd_id: Идентификатор объекта залога в GD.
        pledge_cadastral_number: Кадастровый номер объекта залога.
        order_kind_id: Идентификатор вида запроса.
        email_for_answer: Email для отправки результата.
    """

    pledge_gd_id: int | None = Field(
        default=None, description="Идентификатор объекта залога в GD."
    )
    pledge_cadastral_number: str | None = Field(
        default=None, description="Кадастровый номер объекта залога."
    )
    order_kind_id: int | None = Field(
        default=None, description="Идентификатор вида запроса."
    )
    email_for_answer: str | None = Field(
        default=None, description="Электронная почта для отправки ответа."
    )


class OrderSchemaOut(OrderSchemaIn):
    """
    Схема для исходящих данных заказа.

    Attributes:
        id: Уникальный идентификатор заказа.
        order_kind_id: Идентификатор вида запроса.
        order_kind: Информация о виде запроса.
        is_active: Флаг активности заказа.
        is_send_to_gd: Флаг отправки результата в ГД.
        errors: Ошибки обработки заказа.
        response_data: Данные ответа по заказу.
        object_uuid: UUID объекта заказа.
        created_at: Дата создания заказа.
        updated_at: Дата последнего обновления заказа.
        files: Список файлов, связанных с заказом.
    """

    id: int = Field(..., description="Идентификатор запроса.")
    order_kind_id: int | None = Field(
        default=None, description="Идентификатор вида запроса."
    )
    order_kind: OrderKindSchemaOut | None = Field(
        default=None, description="Информация о виде запроса."
    )
    is_active: bool = Field(default=True, description="Активен ли запрос.")
    is_send_to_gd: bool = Field(default=False, description="Отправлен ли запрос в ГД.")
    errors: dict[str, Any] | str | None = Field(
        default=None, description="Сообщения об ошибках."
    )
    response_data: dict[str, Any] | str | None = Field(
        default=None, description="Данные ответа."
    )
    object_uuid: UUID = Field(..., description="UUID объекта.")
    created_at: datetime = Field(..., description="Дата создания.")
    updated_at: datetime = Field(..., description="Дата последнего обновления.")
    files: list[FileSchemaOut] = Field(
        default_factory=list, description="Список файлов, связанных с запросом."
    )


class OrderVersionSchemaOut(OrderSchemaOut):
    """
    Схема версии заказа.

    Attributes:
        operation_type: Тип операции.
        transaction_id: Идентификатор транзакции.
    """

    operation_type: int = Field(..., description="Тип операции.")
    transaction_id: int = Field(..., description="Идентификатор транзакции.")


class OrderIdQuerySchema(BaseSchema):
    """
    Query-схема для action-роутов, где order_id передаётся в query string.

    Attributes:
        order_id: Идентификатор заказа.
    """

    order_id: int = Field(description="Идентификатор заказа.")


class OrderIdPathSchema(BaseSchema):
    """
    Path-схема для action-роутов, где order_id передаётся в path.

    Attributes:
        order_id: Идентификатор заказа.
    """

    order_id: int = Field(description="Идентификатор заказа.")
