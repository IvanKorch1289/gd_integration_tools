"""S168 W14 P2-10: UserAdmin для модели User.

S168 W14 P2-10: moved from src/backend/utilities/admin_panel/users.py
to extensions/core_entities/users/admin.py per master prompt v8 P2-10.
"""

from sqladmin import ModelView

from extensions.core_entities.users.domain.models import User
from src.backend.utilities.admin_panel.base import BaseAdmin

__all__ = ("UserAdmin",)


class UserAdmin(ModelView, BaseAdmin, model=User):
    """
    Административная панель для модели User.

    Атрибуты:
        column_list (List[str]): Список колонок, отображаемых в таблице.
        column_searchable_list (List[str]): Список колонок, по которым можно выполнять поиск.
        column_sortable_list (List[str]): Список колонок, по которым можно сортировать.
        column_filters (List[str]): Список колонок, по которым можно фильтровать.
        form_create_rules (List[str]): Список полей, отображаемых в форме создания.
    """

    column_list = ["id", "username", "email", "is_superuser", "is_active", "created_at", "updated_at"]
    column_searchable_list = ["id", "username", "email"]
    column_sortable_list = ["id", "username", "email", "created_at", "updated_at"]
    column_filters = ["is_superuser", "is_active"]
    form_create_rules = ["username", "email", "is_superuser", "is_active"]
