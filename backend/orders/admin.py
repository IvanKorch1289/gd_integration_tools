from typing import List

from sqladmin import ModelView

from backend.base import BaseAdmin
from backend.orders.models import Order


__all__ = ("OrderAdmin",)


class OrderAdmin(BaseAdmin, ModelView, model=Order):
    column_list: List[str] = [
        "id",
        "object_uuid",
        "pledge_cadastral_number",
        "pledge_gd_id",
        "created_at",
        "updated_at",
    ]
    column_searchable_list: List[str] = [
        "id",
        "object_uuid",
        "pledge_cadastral_number",
        "pledge_gd_id",
    ]
    column_sortable_list: List[str] = [
        "id",
        "object_uuid",
        "pledge_cadastral_number",
        "pledge_gd_id",
        "created_at",
        "updated_at",
    ]
    page_size: int = 50
    page_size_options: List[int] = [25, 50, 100, 200]
    column_filters = ["object_uuid", "pledge_cadastral_number", "pledge_gd_id"]
    form_create_rules = ["object_uuid", "pledge_cadastral_number", "pledge_gd_id"]
