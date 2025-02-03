from pydantic import BaseModel

from app.repositories.files import FileRepository, get_file_repo
from app.schemas.route_schemas.files import (
    FileSchemaIn,
    FileSchemaOut,
    FileVersionSchemaOut,
)
from app.services.route_services.base import BaseService


__all__ = ("get_file_service",)


class FileService(BaseService[FileRepository]):
    """
    Сервис для работы с файлами. Обеспечивает создание, обновление, получение и обработку файлов
    """

    def __init__(
        self,
        schema_in: BaseModel,
        schema_out: BaseModel,
        version_schema: BaseModel,
        repo: FileRepository,
    ):
        """
        Инициализация сервиса файлов.

        :param response_schema: Схема для преобразования данных в ответ.
        :param request_schema: Схема для валидации входных данных.
        :param version_schema: Схема для валидации выходных данных версии.
        :param repo: Репозиторий для работы с файлами.
        """
        super().__init__(
            repo=repo,
            request_schema=schema_in,
            response_schema=schema_out,
            version_schema=version_schema,
        )


def get_file_service() -> FileService:
    """
    Возвращает экземпляр сервиса для работы с видами заказов.

    Используется как зависимость в FastAPI для внедрения сервиса в маршруты.

    :return: Экземпляр OrderKindService.
    """
    return FileService(
        repo=get_file_repo(),
        schema_in=FileSchemaIn,
        schema_out=FileSchemaOut,
        version_schema=FileVersionSchemaOut,
    )
