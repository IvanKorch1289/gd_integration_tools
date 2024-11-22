from gd_advanced_tools.models import File
from gd_advanced_tools.repository.base import SQLAlchemyRepository
from gd_advanced_tools.schemas import FileSchemaOut

__all__ = ("FileRepository",)


class FileRepository(SQLAlchemyRepository):
    model = File
    response_schema = FileSchemaOut
