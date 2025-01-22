from fastapi_filter.contrib.sqlalchemy import Filter
from pydantic import Field, SecretStr

from backend.users.models import User


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
