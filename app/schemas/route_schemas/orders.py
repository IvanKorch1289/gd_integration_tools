from datetime import datetime
from typing import Dict, List, Union
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.schemas.route_schemas.files import FileSchemaOut
from app.schemas.route_schemas.orderkinds import OrderKindSchemaOut


__all__ = (
    "OrderSchemaIn",
    "OrderSchemaOut",
    "OrderVersionSchemaOut",
)


class OrderSchemaIn(BaseSchema):
    """
    Схема для входящих данных заказа.

    Атрибуты:
        pledge_gd_id (int | None): Идентификатор объекта залога в GD. По умолчанию None.
        pledge_cadastral_number (str): Кадастровый номер объекта залога. По умолчанию None.
        order_kind_id (str): Идентификатор вида запроса. По умолчанию None.
        email_for_answer (str): Электронная почта для отправки ответа. По умолчанию None.
    """

    pledge_gd_id: int | None = Field(
        None, description="Идентификатор объекта залога в GD"
    )
    pledge_cadastral_number: str = Field(
        None, description="Кадастровый номер объекта залога"
    )
    order_kind_id: str = Field(None, description="Идентификатор вида запроса")
    email_for_answer: str = Field(
        None, description="Электронная почта для отправки ответа"
    )


class OrderSchemaOut(OrderSchemaIn):
    """
    Схема для исходящих данных заказа.

    Наследует атрибуты из OrderSchemaIn и добавляет дополнительные поля.

    Атрибуты:
        id (int): Уникальный идентификатор заказа.
        order_kind_id (int): Идентификатор вида запроса.
        order_kind (OrderKindSchemaOut): Информация о виде запроса.
        is_active (bool): Активен ли заказ. По умолчанию True.
        is_send_to_gd (bool): Отправлен ли заказ в ГД. По умолчанию False.
        errors (str | None): Сообщения об ошибках. По умолчанию None.
        response_data (dict | None): Данные ответа. По умолчанию None.
        object_uuid (UUID): UUID объекта.
        created_at (datetime): Дата создания заказа.
        updated_at (datetime): Дата последнего обновления заказа.
        files (List[FileSchemaOut] | None): Список файлов, связанных с заказом. По умолчанию пустой список.
    """

    id: int = Field(..., description="Идентификатор запроса")
    order_kind_id: int = Field(None, description="Идентификатор вида запроса")
    order_kind: OrderKindSchemaOut = Field(
        None, description="Информация о виде запроса"
    )
    is_active: bool = Field(True, description="Активен ли запрос")
    is_send_to_gd: bool = Field(False, description="Отправлен ли запрос в ГД")
    errors: Union[Dict, str, None] = Field(
        None, description="Сообщения об ошибках"
    )
    response_data: Union[Dict, str, None] = Field(
        None, description="Данные ответа"
    )
    object_uuid: UUID = Field(..., description="UUID объекта")
    created_at: datetime = Field(..., description="Дата создания")
    updated_at: datetime = Field(..., description="Дата последнего обновления")
    files: List[FileSchemaOut] | None = Field(
        [], description="Список файлов, связанных с запросом"
    )


class OrderVersionSchemaOut(OrderSchemaOut):
    """
    Схема для исходящих данных версии заказа.

    Наследует атрибуты из OrderSchemaOut и добавляет дополнительные поля.

    Атрибуты:
        operation_type (int): Тип операции (создание, обновление, удаление).
        transaction_id (int): Идентификатор транзакции.
    """

    operation_type: int
    transaction_id: int
