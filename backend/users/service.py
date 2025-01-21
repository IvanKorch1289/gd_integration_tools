from typing import Any, Dict, Union

from fastapi_filter.contrib.sqlalchemy import Filter

from backend.base.service import BaseService
from backend.users.repository import UserRepository
from backend.users.schemas import UserSchemaIn, UserSchemaOut


__all__ = ("UserService",)


class UserService(BaseService):
    """
    Сервис для работы с пользователями. Обеспечивает создание, аутентификацию и управление пользователями.

    Атрибуты:
        repo (UserRepository): Репозиторий для работы с таблицей пользователей.
        response_schema (Type[UserSchemaOut]): Схема для преобразования данных в ответ.
        request_schema (Type[UserSchemaIn]): Схема для валидации входных данных.
    """

    repo = UserRepository()
    response_schema = UserSchemaOut
    request_schema = UserSchemaIn

    async def add(self, data: Dict[str, Any]) -> Union[UserSchemaOut, str]:
        """
        Добавляет нового пользователя.

        :param data: Словарь с данными для создания пользователя.
        :return: Созданный пользователь в виде схемы или сообщение об ошибке, если пользователь уже существует.
        :raises Exception: Если произошла ошибка при добавлении пользователя.
        """
        try:
            user = await self.repo.get_by_username(data=data)
            if user:
                return "The user with the specified login already exists."
            # data["password"] = await utilities.hash_password(data["password"])  # Хэширование пароля (если требуется)
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
            data = filter.model_dump()
            user = await self.repo.get_by_username(data=data)
            if user and user.verify_password(password=data["password"]):
                return True
            return False
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком
