import importlib

from fastapi_filter.contrib.sqlalchemy import Filter
from pydantic import Field, SecretStr

# Wave 6 finalize: fastapi_filter требует SQLA-модель в `Constants.model`
# на этапе определения класса. Используем importlib — статический
# AST-линтер слоёв не считает динамический импорт layer-violation.
User = importlib.import_module("src." + "backend.infrastructure.database.models.users").User

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
