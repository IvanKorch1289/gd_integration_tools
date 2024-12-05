from typing import List

from sqladmin import ModelView

from gd_advanced_tools.users.models import User


__all__ = ("UserAdmin",)


class UserAdmin(ModelView, model=User):
    column_searchable_list: List[str] = ["id", "username", "email"]
    column_sortable_list: List[str] = [
        "id",
        "username",
        "email",
        "created_at",
        "updated_at",
    ]
    page_size: int = 20
