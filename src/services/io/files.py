from pydantic import BaseModel

from app.core.decorators.singleton import singleton
from app.infrastructure.repositories.files import FileRepository, get_file_repo
from app.schemas.route_schemas.files import (
    FileSchemaIn,
    FileSchemaOut,
    FileVersionSchemaOut,
)
from app.services.core.base import BaseService

__all__ = ("get_file_service",)


@singleton
class FileService(
    BaseService[FileRepository, FileSchemaOut, FileSchemaIn, FileVersionSchemaOut]
):
    """
    Сервис для работы с файлами. Обеспечивает создание, обновление, получение и обработку файлов.
    """

    def __init__(
        self,
        schema_in: type[BaseModel],
        schema_out: type[BaseModel],
        version_schema: type[BaseModel],
        repo: FileRepository,
    ) -> None:
        super().__init__(
            repo=repo,
            request_schema=schema_in,
            response_schema=schema_out,
            version_schema=version_schema,
        )


def get_file_service() -> FileService:
    """
    Возвращает экземпляр сервиса для работы с файлами.
    """
    return FileService(
        repo=get_file_repo(),
        schema_in=FileSchemaIn,
        schema_out=FileSchemaOut,
        version_schema=FileVersionSchemaOut,
    )
