from gd_advanced_tools.repository import FileRepository
from gd_advanced_tools.schemas import FileSchemaOut
from gd_advanced_tools.services.base import BaseService


__all__ = ('FileService', )


class FileService(BaseService):

    repo = FileRepository()
    response_schema = FileSchemaOut
