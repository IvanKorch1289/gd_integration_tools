from typing import List

from sqladmin import ModelView

from backend.base import BaseAdmin
from backend.files.models import File, OrderFile


__all__ = (
    "FileAdmin",
    "OrderFileAdmin",
)


class FileAdmin(BaseAdmin, ModelView, model=File):
    column_list: List[str] = ["id", "object_uuid", "name", "created_at", "updated_at"]
    column_searchable_list: List[str] = ["id", "name", "object_uuid"]
    column_sortable_list: List[str] = [
        "id",
        "name",
        "object_uuid",
        "created_at",
        "updated_at",
    ]
    column_filters = ["object_uuid", "name"]
    form_create_rules = ["object_uuid", "name"]


class OrderFileAdmin(BaseAdmin, ModelView, model=OrderFile):
    column_list: List[str] = ["id", "order_id", "file_id"]
    column_searchable_list: List[str] = ["id", "order_id", "file_id"]
    column_sortable_list: List[str] = [
        "id",
        "order_id",
        "file_id",
        "created_at",
        "updated_at",
    ]
    column_filters = ["order_id", "file_id"]
    form_create_rules = ["order_id", "file_id"]
