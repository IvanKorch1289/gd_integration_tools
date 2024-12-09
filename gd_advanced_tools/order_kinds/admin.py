from typing import List

from sqladmin import ModelView

from gd_advanced_tools.order_kinds.models import OrderKind


__all__ = ("OrderKindAdmin",)


class OrderKindAdmin(ModelView, model=OrderKind):
    column_list: List[str] = ["id", "name", "skb_uuid", "created_at", "updated_at"]
    column_searchable_list: List[str] = ["id", "name", "skb_uuid"]
    column_sortable_list: List[str] = [
        "id",
        "name",
        "skb_uuid",
        "created_at",
        "updated_at",
    ]
    page_size: int = 20
    column_filters = ["name", "skb_uuid"]
    can_create = True
    can_edit = True
    can_delete = True
