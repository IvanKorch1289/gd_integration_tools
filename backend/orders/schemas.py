from datetime import datetime
from typing import List
from uuid import UUID

from pydantic import Field

from backend.base.schemas import PublicSchema
from backend.files.schemas import FileSchemaOut
from backend.orderkinds.schemas import OrderKindSchemaOut


__all__ = (
    "OrderSchemaIn",
    "OrderSchemaOut",
)


class OrderSchemaIn(PublicSchema):

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

    id: int = Field(..., description="Идентификатор запроса")
    order_kind_id: int = Field(None, description="Идентификатор вида запроса")
    order_kind: OrderKindSchemaOut = Field(
        None, description="Информация о виде запроса"
    )
    is_active: bool = Field(True, description="Активен ли запроса")
    is_send_to_gd: bool = Field(False, description="Отправлен ли запроса в ГД")
    errors: str | None = Field(None, description="Сообщения об ошибках")
    response_data: dict | None = Field(None, description="Данные ответа")
    object_uuid: UUID = Field(..., description="UUID объекта")
    created_at: datetime = Field(..., description="Дата создания")
    updated_at: datetime = Field(..., description="Дата последнего обновления")
    files: List[FileSchemaOut] | None = Field(
        [], description="Список файлов, связанных с запроса"
    )
