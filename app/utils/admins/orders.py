from typing import List

from sqladmin import ModelView

from app.infra.db.models.orders import Order
from app.utils.admins.base import BaseAdmin


__all__ = ("OrderAdmin",)


class OrderAdmin(ModelView, BaseAdmin, model=Order):  # type: ignore
    """
    Административная панель для модели Order.

    Атрибуты:
        column_list (List[str]): Список колонок, отображаемых в таблице.
        column_searchable_list (List[str]): Список колонок, по которым можно выполнять поиск.
        column_sortable_list (List[str]): Список колонок, по которым можно сортировать.
        page_size (int): Количество элементов на странице по умолчанию.
        page_size_options (List[int]): Список доступных вариантов количества элементов на странице.
        column_filters (List[str]): Список колонок, по которым можно фильтровать.
        form_create_rules (List[str]): Список полей, отображаемых в форме создания.
    """

    column_list: List[str] = [  # type: ignore
        "id",
        "object_uuid",
        "pledge_cadastral_number",
        "pledge_gd_id",
        "created_at",
        "updated_at",
    ]
    column_searchable_list: List[str] = [  # type: ignore
        "id",
        "object_uuid",
        "pledge_cadastral_number",
        "pledge_gd_id",
    ]
    column_sortable_list: List[str] = [  # type: ignore
        "id",
        "object_uuid",
        "pledge_cadastral_number",
        "pledge_gd_id",
        "created_at",
        "updated_at",
    ]
    column_filters: List[str] = [
        "object_uuid",
        "pledge_cadastral_number",
        "pledge_gd_id",
    ]
    form_create_rules: List[str] = [  # type: ignore
        "object_uuid",
        "pledge_cadastral_number",
        "pledge_gd_id",
    ]
