from typing import List

from sqladmin import ModelView

from backend.base import BaseAdmin
from backend.orders.models import Order


__all__ = ("OrderAdmin",)


class OrderAdmin(BaseAdmin, ModelView, model=Order):
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
    column_filters: List[str] = [
        "object_uuid",
        "pledge_cadastral_number",
        "pledge_gd_id",
    ]
    form_create_rules: List[str] = [
        "object_uuid",
        "pledge_cadastral_number",
        "pledge_gd_id",
    ]
