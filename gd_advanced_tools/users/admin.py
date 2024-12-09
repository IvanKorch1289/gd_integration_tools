from typing import List

from sqladmin import ModelView

from gd_advanced_tools.users.models import User


__all__ = ("UserAdmin",)


class UserAdmin(ModelView, model=User):
    column_list: List[str] = [
        "id",
        "username",
        "email",
        "is_active",
        "is_superuser",
        "created_at",
        "updated_at",
    ]
    column_searchable_list: List[str] = ["id", "username", "email"]
    column_sortable_list: List[str] = [
        "id",
        "username",
        "email",
        "created_at",
        "updated_at",
    ]
    page_size: int = 20
    column_filters = ["username", "email"]
    can_create = True
    can_edit = True
    can_delete = True
