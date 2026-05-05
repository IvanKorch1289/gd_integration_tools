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

__all__ = ("get_user_service",)


_REPO_USERS_MOD = "src." + "backend.infrastructure.repositories.users"


class UserService(
    BaseService[
        UserRepositoryProtocol, UserSchemaOut, UserSchemaIn, UserVersionSchemaOut
    ]
):
    """
    Сервис для работы с пользователями. Обеспечивает создание, аутентификацию и управление пользователями.
    """

    async def _get_user_by_username(self, data: dict[str, Any]) -> Any:
        """
        Вспомогательный метод для поиска пользователя по имени.
        """
        try:
            return await self.repo.get_by_username(data=data)
        except Exception as exc:
            raise ServiceError from exc

    async def add(self, data: dict[str, Any]) -> UserSchemaOut | None:
        """
        Добавляет нового пользователя.

        Args:
            data: Словарь с данными для создания пользователя.

        Returns:
            UserSchemaOut: Созданный пользователь в виде схемы.

        Raises:
            ValueError: Если пользователь с таким логином уже существует.
            ServiceError: Если произошла ошибка при добавлении пользователя.
        """
        try:
            user = await self._get_user_by_username(data=data)
            if user:
                # ВМЕСТО ВОЗВРАТА СТРОКИ бросаем исключение, чтобы не сломать Response Model.
                raise ValueError("The user with the specified login already exists.")

            return await super().add(data=data)
        except ValueError:
            raise
        except Exception as exc:
            raise ServiceError from exc

    async def login(self, data: dict[str, Any]) -> bool:
        """
        Аутентифицирует пользователя.

        Args:
            data: Словарь с данными для авторизации (должен содержать 'password' и поля для логина).

        Returns:
            bool: True, если аутентификация успешна, иначе False.

        Raises:
            ServiceError: Если произошла ошибка при аутентификации.
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
    """
    Возвращает экземпляр сервиса для работы с пользователями.
    """
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
