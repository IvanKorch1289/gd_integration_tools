from uuid import UUID

from fastapi_filter.contrib.sqlalchemy import Filter

from gd_advanced_tools.models import File


__all__ = ('FileFilter', )


class FileFilter(Filter):
    name: str | None = None
    object_uuid__like: UUID | None = None

    class Constants(Filter.Constants):
        model = File
