from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.infrastructure.db.models.base import BaseModel
from app.infrastructure.db.models.files import File, OrderFile
from app.infrastructure.db.session_manager import main_session_manager
from app.infrastructure.repositories.base import SQLAlchemyRepository

__all__ = ("FileRepository", "get_file_repo")


class FileRepository(SQLAlchemyRepository):
    """
    Репозиторий для работы с таблицей файлов (File) и связующей таблицей (OrderFile).
    """

    def __init__(
        self,
        model: type[BaseModel],
        load_joined_models: bool,
        link_model: type[BaseModel],
    ) -> None:
        super().__init__(model=model, load_joined_models=load_joined_models)
        self.link_model = link_model

    @main_session_manager.connection()
    async def add_link(self, session: AsyncSession, data: dict[str, Any]) -> BaseModel:
        """
        Добавляет связь между файлом и заказом в связующую таблицу (OrderFile).

        Args:
            session: Асинхронная сессия SQLAlchemy.
            data: Данные для создания связи (содержит order_id и file_id).

        Returns:
            BaseModel: Объект созданной связи.

        Raises:
            NotFoundError: Если связь не удалось создать.
        """
        new_link = self.link_model(**data)

        session.add(new_link)
        await session.flush()
        await session.refresh(new_link)

        if not new_link:
            raise NotFoundError(message="Failed to create link between file and order")

        return new_link


_file_repo_instance: FileRepository | None = None


def get_file_repo() -> FileRepository:
    """
    Возвращает экземпляр репозитория для работы с файлами.
    """
    global _file_repo_instance
    if _file_repo_instance is None:
        _file_repo_instance = FileRepository(model=File, load_joined_models=False, link_model=OrderFile)
    return _file_repo_instance
