from typing import List

from sqladmin import ModelView

from app.infra.db.models.files import File, OrderFile
from app.utils.admins.base import BaseAdmin


__all__ = (
    "FileAdmin",
    "OrderFileAdmin",
)


class FileAdmin(ModelView, BaseAdmin, model=File):  # type: ignore
    """
    Административная панель для модели File.

    Атрибуты:
        column_list (List[str]): Список колонок, отображаемых в таблице.
        column_searchable_list (List[str]): Список колонок, по которым можно выполнять поиск.
        column_sortable_list (List[str]): Список колонок, по которым можно сортировать.
        column_filters (List[str]): Список колонок, по которым можно фильтровать.
        form_create_rules (List[str]): Список полей, отображаемых в форме создания.
    """

    column_list: List[str] = [  # type: ignore
        "id",
        "object_uuid",
        "name",
        "created_at",
        "updated_at",
    ]
    column_searchable_list: List[str] = ["id", "name", "object_uuid"]  # type: ignore
    column_sortable_list: List[str] = [  # type: ignore
        "id",
        "name",
        "object_uuid",
        "created_at",
        "updated_at",
    ]
    column_filters: List[str] = ["object_uuid", "name"]
    form_create_rules: List[str] = ["object_uuid", "name"]  # type: ignore


class OrderFileAdmin(ModelView, BaseAdmin, model=OrderFile):  # type: ignore
    """
    Административная панель для модели OrderFile.

    Атрибуты:
        column_list (List[str]): Список колонок, отображаемых в таблице.
        column_searchable_list (List[str]): Список колонок, по которым можно выполнять поиск.
        column_sortable_list (List[str]): Список колонок, по которым можно сортировать.
        column_filters (List[str]): Список колонок, по которым можно фильтровать.
        form_create_rules (List[str]): Список полей, отображаемых в форме создания.
    """

    column_list: List[str] = ["id", "order_id", "file_id"]  # type: ignore
    column_searchable_list: List[str] = ["id", "order_id", "file_id"]  # type: ignore
    column_sortable_list: List[str] = [  # type: ignore
        "id",
        "order_id",
        "file_id",
        "created_at",
        "updated_at",
    ]
    column_filters: List[str] = ["order_id", "file_id"]
    form_create_rules: List[str] = ["order_id", "file_id"]  # type: ignore
