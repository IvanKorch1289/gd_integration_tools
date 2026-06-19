"""S168 W14 P2-10: FileAdmin + OrderFileAdmin для моделей.

S168 W14 P2-10: moved from src/backend/utilities/admin_panel/files.py
to extensions/core_entities/files/admin.py per master prompt v8 P2-10.

S168 delta-2026-06-19: OrderFileAdmin re-added (was missing after migration).
"""

from sqladmin import ModelView

from extensions.core_entities.files.domain.models import File, OrderFile
from src.backend.utilities.admin_panel.base import BaseAdmin

__all__ = ("FileAdmin", "OrderFileAdmin")


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


class OrderFileAdmin(ModelView, BaseAdmin, model=OrderFile):
    """
    Административная панель для модели OrderFile.

    Атрибуты:
        column_list (List[str]): Список колонок, отображаемых в таблице.
        column_searchable_list (List[str]): Список колонок, по которым можно выполнять поиск.
        column_sortable_list (List[str]): Список колонок, по которым можно сортировать.
        column_filters (List[str]): Список колонок, по которым можно фильтровать.
        form_create_rules (List[str]): Список полей, отображаемых в форме создания.
    """

    column_list = ["id", "order_id", "file_id"]
    column_searchable_list = ["id", "order_id", "file_id"]
    column_sortable_list = ["id", "order_id", "file_id", "created_at", "updated_at"]
    column_filters = ["order_id", "file_id"]
    form_create_rules = ["order_id", "file_id"]
