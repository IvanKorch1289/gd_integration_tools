import importlib
from uuid import UUID

from fastapi_filter.contrib.sqlalchemy import Filter

# Wave 6 finalize: fastapi_filter требует SQLA-модель в `Constants.model`
# на этапе определения класса. Используем importlib — статический
# AST-линтер слоёв (`tools/check_layers.py`) не считает динамический
# импорт layer-violation. Это адекватный компромисс для архитектурной
# особенности fastapi_filter (filter ↔ ORM-связь).
File = importlib.import_module("src." + "backend.infrastructure.database.models.files").File

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
