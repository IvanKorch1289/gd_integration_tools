"""S168 W14 P2-10: FileAdmin для модели File.

S168 W14 P2-10: moved from src/backend/utilities/admin_panel/files.py
to extensions/core_entities/files/admin.py per master prompt v8 P2-10.
"""

from sqladmin import ModelView

from extensions.core_entities.files.domain.models import File
from src.backend.utilities.admin_panel.base import BaseAdmin

__all__ = ("FileAdmin",)


class FileAdmin(ModelView, BaseAdmin, model=File):
    """
    Административная панель для модели File.

    Атрибуты:
        column_list (List[str]): Список колонок, отображаемых в таблице.
        column_searchable_list (List[str]): Список колонок, по которым можно выполнять поиск.
        column_sortable_list (List[str]): Список колонок, по которым можно сортировать.
        column_filters (List[str]): Список колонок, по которым можно фильтровать.
    """

    column_list = ["id", "name", "object_uuid", "created_at", "updated_at"]
    column_searchable_list = ["id", "name", "object_uuid"]
    column_sortable_list = ["id", "name", "created_at", "updated_at"]
    column_filters = ["name"]
