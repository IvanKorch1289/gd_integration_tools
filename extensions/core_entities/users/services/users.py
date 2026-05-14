"""Сервис User (миграция из ядра — Sprint 7, R-V15-16).

Каноническое расположение в V11 plugin layout. Старый модуль
``src.backend.services.core.users`` сохраняется как backward-compat
shim и эмитит DeprecationWarning.
"""

from __future__ import annotations

import importlib
from typing import Any

from src.backend.core.errors import ServiceError
from src.backend.core.interfaces.repositories import UserRepositoryProtocol
from src.backend.schemas.route_schemas.users import (
    UserSchemaIn,
    UserSchemaOut,
    UserVersionSchemaOut,
)
from src.backend.services.core.base import BaseService

__all__ = ("UserService", "get_user_service")


_REPO_USERS_MOD = "extensions.core_entities.users.repositories.users"


class UserService(
    BaseService[
        UserRepositoryProtocol, UserSchemaOut, UserSchemaIn, UserVersionSchemaOut
    ]
):
    """Сервис для работы с пользователями (создание + аутентификация)."""

    async def _get_user_by_username(self, data: dict[str, Any]) -> Any:
        """Поиск пользователя по имени.

        Args:
            data: Словарь с ``username``.

        Returns:
            Объект пользователя или ``None``.

        Raises:
            ServiceError: Если произошла ошибка в репозитории.
        """
        try:
            return await self.repo.get_by_username(data=data)
        except Exception as exc:
            raise ServiceError from exc

    async def add(self, data: dict[str, Any]) -> UserSchemaOut | None:
        """Добавляет нового пользователя.

        Args:
            data: Данные для создания пользователя.

        Returns:
            ``UserSchemaOut`` со созданным пользователем.

        Raises:
            ValueError: Если пользователь с таким логином уже существует.
            ServiceError: Любая иная ошибка добавления.
        """
        try:
            user = await self._get_user_by_username(data=data)
            if user:
                raise ValueError(
                    "The user with the specified login already exists."
                )
            return await super().add(data=data)
        except ValueError:
            raise
        except Exception as exc:
            raise ServiceError from exc

    async def login(self, data: dict[str, Any]) -> bool:
        """Проверяет credentials.

        Args:
            data: Словарь с ``username`` и ``password``.

        Returns:
            ``True`` если credentials валидны, иначе ``False``.

        Raises:
            ServiceError: Если произошла ошибка проверки.
        """
        try:
            user = await self._get_user_by_username(data=data)
            if user and user.verify_password(password=data.get("password")):
                return True
            return False
        except Exception as exc:
            raise ServiceError from exc


_user_service_instance: UserService | None = None


def get_user_service() -> UserService:
    """Возвращает singleton экземпляр :class:`UserService`."""
    global _user_service_instance
    if _user_service_instance is None:
        repo = importlib.import_module(_REPO_USERS_MOD).get_user_repo()
        _user_service_instance = UserService(
            repo=repo,
            request_schema=UserSchemaIn,
            response_schema=UserSchemaOut,
            version_schema=UserVersionSchemaOut,
        )
    return _user_service_instance
