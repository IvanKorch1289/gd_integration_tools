"""S168 W14 P2-10: OrderKindAdmin для модели OrderKind.

S168 W14 P2-10: moved from src/backend/utilities/admin_panel/orderkinds.py
to extensions/core_entities/orderkinds/admin.py per master prompt v8 P2-10.

Per CLAUDE.md V22: бизнес-логика (включая admin) — только в
extensions/<name>/, ядро domain-agnostic.
"""

from sqladmin import ModelView

from extensions.core_entities.orderkinds.domain.models import OrderKind
from src.backend.utilities.admin_panel.base import BaseAdmin

__all__ = ("OrderKindAdmin",)


class OrderKindAdmin(ModelView, BaseAdmin, model=OrderKind):
    """
    Административная панель для модели OrderKind.

    Атрибуты:
        column_list (List[str]): Список колонок, отображаемых в таблице.
        column_searchable_list (List[str]): Список колонок, по которым можно выполнять поиск.
        column_sortable_list (List[str]): Список колонок, по которым можно сортировать.
        column_filters (List[str]): Список колонок, по которым можно фильтровать.
        form_create_rules (List[str]): Список полей, отображаемых в форме создания.
    """

    column_list = ["id", "name", "skb_uuid", "created_at", "updated_at"]
    column_searchable_list = ["id", "name", "skb_uuid"]
    column_sortable_list = ["id", "name", "skb_uuid", "created_at", "updated_at"]
    column_filters = ["name", "skb_uuid"]
    form_create_rules = ["name", "skb_uuid"]
