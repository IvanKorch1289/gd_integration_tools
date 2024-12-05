from typing import List

from sqladmin import ModelView

from gd_advanced_tools.orders.models import Order


__all__ = ("OrderAdmin",)


class OrderAdmin(ModelView, model=Order):
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
    page_size: int = 20
