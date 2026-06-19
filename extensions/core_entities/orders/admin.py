"""S168 W14 P2-10: OrderAdmin для модели Order.

S168 W14 P2-10: moved from src/backend/utilities/admin_panel/orders.py
to extensions/core_entities/orders/admin.py per master prompt v8 P2-10.
"""

from sqladmin import ModelView

from extensions.core_entities.orders.domain.models import Order
from src.backend.utilities.admin_panel.base import BaseAdmin

__all__ = ("OrderAdmin",)


class OrderAdmin(ModelView, BaseAdmin, model=Order):
    """
    Административная панель для модели Order.

    Атрибуты:
        column_list (List[str]): Список колонок, отображаемых в таблице.
        column_searchable_list (List[str]): Список колонок, по которым можно выполнять поиск.
        column_sortable_list (List[str]): Список колонок, по которым можно сортировать.
        column_filters (List[str]): Список колонок, по которым можно фильтровать.
        form_create_rules (List[str]): Список полей, отображаемых в форме создания.
    """

    column_list = ["id", "order_kind", "created_at", "updated_at"]
    column_searchable_list = ["id"]
    column_sortable_list = ["id", "created_at", "updated_at"]
    column_filters = ["order_kind"]
    form_create_rules = ["order_kind"]
