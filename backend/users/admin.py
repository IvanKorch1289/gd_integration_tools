from typing import List

from sqladmin import ModelView

from backend.base import BaseAdmin
from backend.users.models import User


__all__ = ("UserAdmin",)


class UserAdmin(BaseAdmin, ModelView, model=User):
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
    page_size: int = 50
    page_size_options: List[int] = [25, 50, 100, 200]
    column_filters = ["username", "email"]
    form_create_rules = ["username", "password", "email", "is_active", "is_superuser"]
