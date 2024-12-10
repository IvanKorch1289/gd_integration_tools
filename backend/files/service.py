from backend.base.service import BaseService
from backend.files.repository import FileRepository
from backend.files.schemas import FileSchemaOut


__all__ = ("FileService",)


class FileService(BaseService):

    repo = FileRepository()
    response_schema = FileSchemaOut
