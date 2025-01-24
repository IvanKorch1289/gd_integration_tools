from pydantic import BaseModel

from backend.base.service import BaseService
from backend.files.repository import FileRepository, get_file_repo
from backend.files.schemas import FileSchemaIn, FileSchemaOut


__all__ = (
    "FileService",
    "get_file_service",
)


class FileService(BaseService):
    """
    Сервис для работы с файлами.

    Наследует функциональность базового сервиса (BaseService) и использует
    репозиторий FileRepository для взаимодействия с данными файлов.

    Атрибуты:
        repo (FileRepository): Репозиторий для работы с файлами.
        response_schema (FileSchemaOut): Схема для преобразования данных файла в ответ.
        request_schema (FileSchemaIn): Схема для валидации входных данных.
    """

    def __init__(
        self,
        response_schema: BaseModel = None,
        request_schema: BaseModel = None,
        repo: FileRepository = None,
    ):
        """
        Инициализация сервиса для работы с файлами.

        :param repo: Репозиторий для работы с файлами.
        :param response_schema: Схема для преобразования данных файла в ответ.
        :param request_schema: Схема для валидации входных данных.
        """
        super().__init__(
            repo=repo, response_schema=response_schema, request_schema=request_schema
        )


def get_file_service() -> FileService:
    """
    Возвращает экземпляр сервиса для работы с файлами.

    Используется как зависимость в FastAPI для внедрения сервиса в маршруты.

    :return: Экземпляр FileService.
    """
    return FileService(
        repo=get_file_repo(),
        response_schema=FileSchemaOut,
        request_schema=FileSchemaIn,
    )
