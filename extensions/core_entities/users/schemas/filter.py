"""S168 W15 P2-10: filter_schemas для Users.

S168 W15 P2-10: moved from src/backend/schemas/filter_schemas/users.py
to extensions/core_entities/users/schemas/filter.py per master prompt v8 P2-10.
"""

from fastapi_filter.contrib.sqlalchemy import Filter
from pydantic import Field, SecretStr

# S106 W4: User model migrated to extensions/core_entities/users/domain/models/.
# S168 W14 P2-10 closure: updated from legacy src.backend.core.domain.models.users.
from extensions.core_entities.users.domain.models import User  # noqa: E402,F401

__all__ = ("UserFilter", "UserLogin")


class UserFilter(Filter):
    """
    Фильтр для поиска пользователей.

    Атрибуты:
        username__like (str | None): Фильтр по имени пользователя (поиск по частичному совпадению).
    """

    username__like: str | None = None

    class Constants(Filter.Constants):
        """Конфигурация фильтра."""

        model = User  # Модель, к которой применяется фильтр


class UserLogin(Filter):
    """
    Схема для аутентификации пользователя.

    Атрибуты:
        username (str): Имя пользователя.
        password (SecretStr): Пароль пользователя.
    """

    username: str = Field(..., description="Имя пользователя")
    password: SecretStr = Field(..., description="Пароль пользователя")
