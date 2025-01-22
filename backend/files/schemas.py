from datetime import datetime
from uuid import UUID

from backend.base.schemas import PublicSchema


__all__ = ("FileSchemaIn", "FileSchemaOut", "FileKindVersionSchemaOut")


class FileSchemaIn(PublicSchema):
    """
    Схема для входящих данных файла.

    Атрибуты:
        object_uuid (UUID | None): Уникальный идентификатор объекта, связанного с файлом.
                                  По умолчанию None.
    """

    object_uuid: UUID | None = None


class FileSchemaOut(FileSchemaIn):
    """
    Схема для исходящих данных файла.

    Наследует атрибуты из FileSchemaIn и добавляет дополнительные поля.

    Атрибуты:
        id (int): Уникальный идентификатор файла.
        name (str | None): Название файла. Может быть пустым.
        created_at (datetime): Время создания файла.
        updated_at (datetime): Время последнего обновления файла.
    """

    id: int
    name: str | None
    created_at: datetime
    updated_at: datetime


class FileKindVersionSchemaOut(FileSchemaOut):
    """
    Схема для исходящих данных версии данных файла.

    Наследует атрибуты из FileSchemaOut и добавляет дополнительные поля.

    Атрибуты:
        operation_type (int): Тип операции (создание, обновление, удаление).
        transaction_id (int): Идентификатор транзакции.
    """

    operation_type: int
    transaction_id: int
