from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DatabaseError
from app.infrastructure.db.models.users import User
from app.infrastructure.db.session_manager import main_session_manager
from app.infrastructure.repositories.base import SQLAlchemyRepository

__all__ = ("UserRepository", "get_user_repo")


class UserRepository(SQLAlchemyRepository):
    """
    Репозиторий для работы с таблицей пользователей (User).

    Атрибуты:
        model (type[User]): Модель таблицы пользователей.
        load_joined_models (bool): Флаг для загрузки связанных моделей (по умолчанию False).
    """

    def __init__(self, model: Any = User, load_joined_models: bool = False) -> None:
        """
        Инициализация репозитория.

        Args:
            model: Модель таблицы пользователей.
            load_joined_models: Флаг для загрузки связанных моделей.
        """
        super().__init__(model=model, load_joined_models=load_joined_models)

    @main_session_manager.connection()
    async def get_by_username(
        self, session: AsyncSession, data: dict[str, Any]
    ) -> User | None:
        """
        Получает пользователя по имени (username).

        Args:
            session: Асинхронная сессия SQLAlchemy.
            data: Словарь с данными, содержащими имя пользователя.

        Returns:
            User | None: Объект пользователя или None.

        Raises:
            DatabaseError: Если произошла ошибка при получении пользователя.
        """
        try:
            unsecret_data = await self.model.get_value_from_secret_str(data)

            query = select(self.model).where(
                self.model.username == unsecret_data["username"]
            )

            result = await session.execute(query)
            return result.scalars().one_or_none()
        except Exception as exc:
            raise DatabaseError from exc


_user_repo_instance: UserRepository | None = None


def get_user_repo() -> UserRepository:
    """
    Возвращает экземпляр репозитория для работы с пользователями.
    """
    global _user_repo_instance
    if _user_repo_instance is None:
        _user_repo_instance = UserRepository(model=User, load_joined_models=False)
    return _user_repo_instance
