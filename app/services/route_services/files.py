from typing import Type

from app.infra.db.repositories.files import get_file_repo
from app.schemas.route_schemas.files import (
    FileSchemaIn,
    FileSchemaOut,
    FileVersionSchemaOut,
)
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
        version_schema=FileVersionSchemaOut,
    )
