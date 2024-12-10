from datetime import datetime
from uuid import UUID

from backend.base.schemas import PublicSchema


__all__ = (
    "FileSchemaIn",
    "FileSchemaOut",
)


class FileSchemaIn(PublicSchema):

    object_uuid: UUID = None


class FileSchemaOut(FileSchemaIn):

    id: int
    name: str | None
    created_at: datetime
    updated_at: datetime
