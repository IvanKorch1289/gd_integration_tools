from typing import Any, Dict, Union

from fastapi_filter.contrib.sqlalchemy import Filter

from app.db import UserRepository, get_user_repo
from app.schemas import UserSchemaIn, UserSchemaOut
from app.services.service_factory import BaseService


__all__ = ("get_user_service",)


class UserService(BaseService[UserRepository]):
    """
    Сервис для работы с пользователями. Обеспечивает создание, аутентификацию и управление пользователями.

    Атрибуты:
        repo (UserRepository): Репозиторий для работы с таблицей пользователей.
        response_schema (Type[UserSchemaOut]): Схема для преобразования данных в ответ.
        request_schema (Type[UserSchemaIn]): Схема для валидации входных данных.
    """

    async def _get_user_by_username(self, data: Dict[str, Any]) -> Any:
        """
        Вспомогательный метод для поиска пользователя по имени.

        :param data: Словарь с данными для поиска пользователя.
        :return: Найденный пользователь или None, если пользователь не найден.
        """
        return await self.repo.get_by_username(data=data)

    async def add(self, data: Dict[str, Any]) -> Union[UserSchemaOut, str]:
        """
        Добавляет нового пользователя.

        :param data: Словарь с данными для создания пользователя.
        :return: Созданный пользователь в виде схемы или сообщение об ошибке, если пользователь уже существует.
        :raises Exception: Если произошла ошибка при добавлении пользователя.
        """
        try:
            # Проверяем, существует ли пользователь с таким именем
            user = await self._get_user_by_username(data=data)
            if user:
                return "The user with the specified login already exists."

            # Создаем пользователя через базовый метод
            return await super().add(data=data)
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def login(self, filter: Filter) -> bool:
        """
        Аутентифицирует пользователя.

        :param filter: Фильтр для поиска пользователя по имени.
        :return: True, если аутентификация успешна, иначе False.
        :raises Exception: Если произошла ошибка при аутентификации.
        """
        try:
            # Преобразуем фильтр в словарь
            data = filter.model_dump()

            # Ищем пользователя по имени
            user = await self._get_user_by_username(data=data)

            # Проверяем пароль
            if user and user.verify_password(password=data["password"]):
                return True
            return False
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком


def get_user_service() -> UserService:
    """
    Возвращает экземпляр сервиса для работы с пользователями.

    Используется как зависимость в FastAPI для внедрения сервиса в маршруты.

    :return: Экземпляр UserService.
    """
    return UserService(
        repo=get_user_repo(),
        response_schema=UserSchemaOut,
        request_schema=UserSchemaIn,
    )
