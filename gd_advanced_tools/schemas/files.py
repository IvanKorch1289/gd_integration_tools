from datetime import datetime
from uuid import UUID

from gd_advanced_tools.schemas.base import PublicModel


__all__ = ('FileSchemaIn', 'FileSchemaOut', )


class FileSchemaIn(PublicModel):

    object_uuid: UUID = None
    linked_object_id: int | None = None


class FileSchemaOut(FileSchemaIn):

    id: int
    name: str | None
    object_uuid: UUID
    created_at: datetime
    updated_at: datetime
