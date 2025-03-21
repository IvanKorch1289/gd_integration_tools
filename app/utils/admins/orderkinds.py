from typing import List

from sqladmin import ModelView

from app.infra.db.models.orderkinds import OrderKind
from app.utils.admins.base import BaseAdmin


__all__ = ("OrderKindAdmin",)


class OrderKindAdmin(ModelView, BaseAdmin, model=OrderKind):  # type: ignore
    """
    Административная панель для модели OrderKind.

    Атрибуты:
        column_list (List[str]): Список колонок, отображаемых в таблице.
        column_searchable_list (List[str]): Список колонок, по которым можно выполнять поиск.
        column_sortable_list (List[str]): Список колонок, по которым можно сортировать.
        column_filters (List[str]): Список колонок, по которым можно фильтровать.
        form_create_rules (List[str]): Список полей, отображаемых в форме создания.
    """

    column_list: List[str] = [  # type: ignore
        "id",
        "name",
        "skb_uuid",
        "created_at",
        "updated_at",
    ]
    column_searchable_list: List[str] = ["id", "name", "skb_uuid"]  # type: ignore
    column_sortable_list: List[str] = [  # type: ignore
        "id",
        "name",
        "skb_uuid",
        "created_at",
        "updated_at",
    ]
    column_filters: List[str] = ["name", "skb_uuid"]
    form_create_rules: List[str] = ["name", "skb_uuid"]  # type: ignore
