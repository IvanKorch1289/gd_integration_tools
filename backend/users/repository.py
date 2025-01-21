from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.base.repository import SQLAlchemyRepository
from backend.core.database import session_manager
from backend.core.errors import DatabaseError, NotFoundError
from backend.users.models import User
from backend.users.schemas import UserSchemaOut


__all__ = ("UserRepository",)


class UserRepository(SQLAlchemyRepository):
    """
    Репозиторий для работы с таблицей пользователей (User).

    Атрибуты:
        model (Type[User]): Модель таблицы пользователей.
        response_schema (Type[UserSchemaOut]): Схема для преобразования данных в ответ.
    """

    model = User
    response_schema = UserSchemaOut

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_by_username(
        self, session: AsyncSession, data: Dict[str, Any]
    ) -> Optional[User]:
        """
        Получает пользователя по имени пользователя (username).

        :param session: Асинхронная сессия SQLAlchemy.
        :param data: Словарь с данными, содержащими имя пользователя.
        :return: Объект пользователя или None, если пользователь не найден.
        :raises NotFoundError: Если пользователь не найден.
        :raises DatabaseError: Если произошла ошибка при получении пользователя.
        """
        try:
            # Преобразуем данные, удаляя секретные значения (если есть)
            unsecret_data = await self.model.get_value_from_secret_str(data)

            # Формируем запрос для поиска пользователя по имени
            query = select(self.model).where(
                self.model.username == unsecret_data["username"]
            )

            # Выполняем запрос и возвращаем результат
            result = await session.execute(query)
            return result.scalars().one_or_none()
        except Exception as exc:
            raise DatabaseError(message=f"Failed to get user by username: {str(exc)}")
