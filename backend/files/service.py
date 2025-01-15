from backend.base.service import BaseService
from backend.files.repository import FileRepository
from backend.files.schemas import FileSchemaOut


__all__ = ("FileService",)


class FileService(BaseService):
    """
    Сервис для работы с файлами.

    Наследует функциональность базового сервиса (BaseService) и использует
    репозиторий FileRepository для взаимодействия с данными файлов.

    Атрибуты:
        repo (FileRepository): Репозиторий для работы с файлами.
        response_schema (FileSchemaOut): Схема для преобразования данных файла в ответ.
    """

    repo = FileRepository()
    response_schema = FileSchemaOut
