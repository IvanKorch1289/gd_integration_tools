from gd_advanced_tools.base.service import BaseService
from gd_advanced_tools.files.repository import FileRepository
from gd_advanced_tools.files.schemas import FileSchemaOut


__all__ = ("FileService",)


class FileService(BaseService):

    repo = FileRepository()
    response_schema = FileSchemaOut
