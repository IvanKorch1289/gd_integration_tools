from sqladmin import ModelView

from src.infrastructure.database.models.orders import Order
from src.utilities.admin_panel.base import BaseAdmin

__all__ = ("OrderAdmin",)


class OrderAdmin(ModelView, BaseAdmin, model=Order):
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

    column_list = [
        "id",
        "object_uuid",
        "pledge_cadastral_number",
        "pledge_gd_id",
        "created_at",
        "updated_at",
    ]
    column_searchable_list = [
        "id",
        "object_uuid",
        "pledge_cadastral_number",
        "pledge_gd_id",
    ]
    column_sortable_list = [
        "id",
        "object_uuid",
        "pledge_cadastral_number",
        "pledge_gd_id",
        "created_at",
        "updated_at",
    ]
    column_filters = ["object_uuid", "pledge_cadastral_number", "pledge_gd_id"]
    form_create_rules = ["object_uuid", "pledge_cadastral_number", "pledge_gd_id"]
