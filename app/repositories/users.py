from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.models.users import User
from app.repositories.base import SQLAlchemyRepository
from app.utils.decorators.sessioning import session_manager
from app.utils.decorators.singleton import singleton


__all__ = (
    "UserRepository",
    "get_user_repo",
)


@singleton
class UserRepository(SQLAlchemyRepository):
    """
    Репозиторий для работы с таблицей пользователей (User).

    Атрибуты:
        model (Type[User]): Модель таблицы пользователей.
        load_joined_models (bool): Флаг для загрузки связанных моделей (по умолчанию False).
    """

    def __init__(self, model: Any = User, load_joined_models: bool = False):
        """
        Инициализация репозитория.

        :param model: Модель таблицы пользователей.
        :param load_joined_models: Флаг для загрузки связанных моделей.
        """
        super().__init__(model=model, load_joined_models=load_joined_models)

    @session_manager.connection()
    async def get_by_username(
        self, session: AsyncSession, data: Dict[str, Any]
    ) -> User | None:
        """
        Получает пользователя по имени пользователя (username).

        :param session: Асинхронная сессия SQLAlchemy.
        :param data: Словарь с данными, содержащими имя пользователя.
        :return: Объект пользователя или None, если пользователь не найден.
        :raises NotFoundError: Если пользователь не найден.
        :raises DatabaseError: Если произошла ошибка при получении пользователя.
        """
        # Преобразуем данные, удаляя секретные значения (если есть)
        unsecret_data = await self.model.get_value_from_secret_str(data)

        # Формируем запрос для поиска пользователя по имени
        query = select(self.model).where(
            self.model.username == unsecret_data["username"]
        )

        # Выполняем запрос и возвращаем результат
        result = await session.execute(query)
        return result.scalars().one_or_none()


def get_user_repo() -> UserRepository:
    """
    Возвращает экземпляр репозитория для работы с пользователями.

    Используется как зависимость в FastAPI для внедрения репозитория в сервисы или маршруты.

    :return: Экземпляр UserRepository.
    """
    return UserRepository(
        model=User,
        load_joined_models=False,
    )
