from typing import List

from sqladmin import ModelView

from app.infra import User
from app.utils.admins.base import BaseAdmin


__all__ = ("UserAdmin",)


class UserAdmin(BaseAdmin, ModelView, model=User):
    """
    Административный интерфейс для модели User.

    Атрибуты:
        column_list (List[str]): Список колонок, отображаемых в таблице.
        column_searchable_list (List[str]): Список колонок, по которым возможен поиск.
        column_sortable_list (List[str]): Список колонок, по которым возможна сортировка.
        page_size (int): Количество записей на странице по умолчанию.
        page_size_options (List[int]): Варианты количества записей на странице.
        column_filters (List[str]): Список колонок, по которым возможна фильтрация.
        form_create_rules (List[str]): Список полей, отображаемых в форме создания.
    """

    # Список колонок для отображения в таблице
    column_list: List[str] = [
        "id",
        "username",
        "email",
        "is_active",
        "is_superuser",
        "created_at",
        "updated_at",
    ]

    # Список колонок, по которым возможен поиск
    column_searchable_list: List[str] = ["id", "username", "email"]

    # Список колонок, по которым возможна сортировка
    column_sortable_list: List[str] = [
        "id",
        "username",
        "email",
        "created_at",
        "updated_at",
    ]

    # Количество записей на странице по умолчанию
    page_size: int = 50

    # Варианты количества записей на странице
    page_size_options: List[int] = [25, 50, 100, 200]

    # Список колонок, по которым возможна фильтрация
    column_filters = ["username", "email"]

    # Список полей, отображаемых в форме создания
    form_create_rules = ["username", "password", "email", "is_active", "is_superuser"]
