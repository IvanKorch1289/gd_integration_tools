"""S168 W15 P2-10: filter_schemas для Files.

S168 W15 P2-10: moved from src/backend/schemas/filter_schemas/files.py
to extensions/core_entities/files/schemas/filter.py per master prompt v8 P2-10.
"""

from uuid import UUID

from fastapi_filter.contrib.sqlalchemy import Filter

# S106 W4: File model migrated to extensions/core_entities/files/domain/models/.
# S168 W14 P2-10 closure: updated from legacy src.backend.core.domain.models.files.
from extensions.core_entities.files.domain.models import File  # noqa: E402,F401

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
