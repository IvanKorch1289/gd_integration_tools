from uuid import UUID

from fastapi_filter.contrib.sqlalchemy import Filter

from backend.files.models import File


__all__ = ("FileFilter",)


class FileFilter(Filter):
    """
    Фильтр для модели File.

    Атрибуты:
        name (str | None): Фильтр по имени файла.
        object_uuid__like (UUID | None): Фильтр по UUID объекта с использованием оператора LIKE.

    Константы:
        model: Модель, к которой применяется фильтр.
    """

    name: str | None = None
    object_uuid__like: UUID | None = None

    class Constants(Filter.Constants):
        """
        Константы для фильтра.

        Атрибуты:
            model: Модель, к которой применяется фильтр.
        """

        model = File
