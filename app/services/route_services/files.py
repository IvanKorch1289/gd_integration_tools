from typing import Type

from app.infra.db import get_file_repo
from app.schemas import FileSchemaIn, FileSchemaOut
from app.services.service_factory import BaseService, create_service_class


__all__ = ("get_file_service",)


def get_file_service() -> Type[BaseService]:
    """
    Возвращает экземпляр сервиса для работы с файлами.

    Используется как зависимость в FastAPI для внедрения сервиса в маршруты.

    :return: Экземпляр FileService.
    """
    return create_service_class(
        repo=get_file_repo(),
        response_schema=FileSchemaOut,
        request_schema=FileSchemaIn,
    )
