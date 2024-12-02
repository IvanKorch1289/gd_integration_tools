from datetime import datetime
from uuid import UUID

from gd_advanced_tools.schemas.base import PublicModel


__all__ = (
    "FileSchemaIn",
    "FileSchemaOut",
)


class FileSchemaIn(PublicModel):

    object_uuid: UUID = None


class FileSchemaOut(FileSchemaIn):

    id: int
    name: str | None
    created_at: datetime
    updated_at: datetime
