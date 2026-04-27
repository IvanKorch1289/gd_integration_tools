from sqladmin import ModelView

from src.infrastructure.database.models.orderkinds import OrderKind
from src.utilities.admins.base import BaseAdmin

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
