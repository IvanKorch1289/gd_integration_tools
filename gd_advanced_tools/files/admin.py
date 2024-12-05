from typing import List

from sqladmin import ModelView

from gd_advanced_tools.files.models import File, OrderFile


__all__ = (
    "FileAdmin",
    "OrderFileAdmin",
)


class FileAdmin(ModelView, model=File):
    column_searchable_list: List[str] = ["id", "name", "object_uuid"]
    column_sortable_list: List[str] = [
        "id",
        "name",
        "object_uuid",
        "created_at",
        "updated_at",
    ]
    page_size: int = 20


class OrderFileAdmin(ModelView, model=OrderFile):
    column_searchable_list: List[str] = ["id", "order_id", "file_id"]
    column_sortable_list: List[str] = [
        "id",
        "order_id",
        "file_id",
        "created_at",
        "updated_at",
    ]
    page_size: int = 20
