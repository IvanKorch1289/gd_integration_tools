from datetime import datetime
from typing import List
from uuid import UUID

from pydantic import Field

from gd_advanced_tools.base.schemas import PublicModel
from gd_advanced_tools.files.schemas import FileSchemaOut


__all__ = (
    "OrderSchemaIn",
    "OrderSchemaOut",
)


class OrderSchemaIn(PublicModel):

    pledge_gd_id: int | None = Field(
        None, description="Идентификатор объекта залога в GD"
    )
    pledge_cadastral_number: str = Field(
        None, description="Кадастровый номер объекта залога"
    )
    order_kind_id: str = Field(None, description="Идентификатор вида запроса")


class OrderSchemaOut(OrderSchemaIn):

    id: int = Field(..., description="Идентификатор запроса")
    is_active: bool = Field(True, description="Активен ли запроса")
    is_send_to_gd: bool = Field(False, description="Отправлен ли запроса в ГД")
    errors: str | None = Field(None, description="Сообщения об ошибках")
    response_data: dict | None = Field(None, description="Данные ответа")
    object_uuid: UUID = Field(..., description="UUID объекта")
    created_at: datetime = Field(..., description="Дата создания")
    updated_at: datetime = Field(..., description="Дата последнего обновления")
    files: List["FileSchemaOut"] = Field(
        [], description="Список файлов, связанных с запроса"
    )
