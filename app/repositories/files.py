from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.models.base import BaseModel
from app.infra.db.models.files import File, OrderFile
from app.repositories.base import SQLAlchemyRepository
from app.utils.decorators.sessioning import session_manager
from app.utils.decorators.singleton import singleton
from app.utils.errors import NotFoundError


__all__ = (
    "FileRepository",
    "get_file_repo",
)


@singleton
class FileRepository(SQLAlchemyRepository):
    """
    Репозиторий для работы с таблицей файлов (File) и связующей таблицей (OrderFile).

    Атрибуты:
        model (Type[ConcreteTable]): Модель таблицы файлов (File).
        link_model (Type[ConcreteTable]): Модель связующей таблицы (OrderFile).
        load_joined_models (bool): Флаг для загрузки связанных моделей (по умолчанию False).
    """

    def __init__(
        self,
        model: BaseModel,
        load_joined_models: bool,
        link_model: BaseModel,
    ):
        """
        Инициализация репозитория.

        :param model: Модель таблицы файлов (File).
        :param load_joined_models: Флаг для загрузки связанных моделей.
        :param link_model: Модель связующей таблицы (OrderFile).
        """
        super().__init__(model=model, load_joined_models=load_joined_models)
        self.link_model = link_model

    @session_manager.connection()
    async def add_link(
        self, session: AsyncSession, data: Dict[str, Any]
    ) -> BaseModel | None:
        """
        Добавляет связь между файлом и заказом в связующую таблицу (OrderFile).

        :param session: Асинхронная сессия SQLAlchemy.
        :param data: Данные для создания связи (содержит order_id и file_id).
        :return: Объект созданной связи или None, если произошла ошибка.
        :raises NotFoundError: Если связь не удалось создать.
        """
        # Создаем новый объект связи
        new_link = self.link_model(**data)

        # Добавляем объект в сессию
        session.add(new_link)
        await session.flush()  # Фиксируем изменения в базе данных

        # Обновляем объект, чтобы получить актуальные данные из базы
        await session.refresh(new_link)

        # Если объект не был создан, выбрасываем исключение
        if not new_link:
            raise NotFoundError(
                message="Failed to create link between file and order"
            )

        return new_link


def get_file_repo() -> FileRepository:
    """
    Возвращает экземпляр репозитория для работы с файлами.

    :return: Экземпляр FileRepository.
    """
    return FileRepository(
        model=File,
        load_joined_models=False,
        link_model=OrderFile,
    )
