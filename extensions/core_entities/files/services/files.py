"""Сервис File (миграция из ядра — Sprint 7, R-V15-16).

Каноническое расположение в V11 plugin layout. Старый модуль
``src.backend.services.io.files`` сохраняется как backward-compat shim
и эмитит DeprecationWarning.
"""

from __future__ import annotations

from pydantic import BaseModel

from src.backend.core.di.providers import get_file_repo_provider
from src.backend.core.interfaces.repositories import FileRepositoryProtocol
from src.backend.schemas.route_schemas.files import (
    FileSchemaIn,
    FileSchemaOut,
    FileVersionSchemaOut,
)
from src.backend.services.core.base import BaseService

__all__ = ("FileService", "get_file_service")


class FileService(
    BaseService[
        FileRepositoryProtocol, FileSchemaOut, FileSchemaIn, FileVersionSchemaOut
    ]
):
    """
    Сервис для работы с файлами. Обеспечивает создание, обновление, получение и обработку файлов.
    """

    def __init__(
        self,
        schema_in: type[BaseModel],
        schema_out: type[BaseModel],
        version_schema: type[BaseModel],
        repo: FileRepositoryProtocol,
    ) -> None:
        super().__init__(
            repo=repo,
            request_schema=schema_in,
            response_schema=schema_out,
            version_schema=version_schema,
        )


_file_service_instance: FileService | None = None


def get_file_service() -> FileService:
    """
    Возвращает экземпляр сервиса для работы с файлами.
    """
    global _file_service_instance
    if _file_service_instance is None:
        _file_service_instance = FileService(
            repo=get_file_repo_provider(),
            schema_in=FileSchemaIn,
            schema_out=FileSchemaOut,
            version_schema=FileVersionSchemaOut,
        )
    return _file_service_instance
