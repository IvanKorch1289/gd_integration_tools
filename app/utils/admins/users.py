from typing import List

from sqladmin import ModelView

from app.infra.db.models.users import User
from app.utils.admins.base import BaseAdmin


__all__ = ("UserAdmin",)


class UserAdmin(ModelView, BaseAdmin, model=User):  # type: ignore
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

    column_list: List[str] = [  # type: ignore
        "id",
        "username",
        "email",
        "is_active",
        "is_superuser",
        "created_at",
        "updated_at",
    ]
    column_searchable_list: List[str] = ["id", "username", "email"]  # type: ignore
    column_sortable_list: List[str] = [  # type: ignore
        "id",
        "username",
        "email",
        "created_at",
        "updated_at",
    ]
    column_filters = ["username", "email"]
    form_create_rules = [
        "username",
        "password",
        "email",
        "is_active",
        "is_superuser",
    ]
