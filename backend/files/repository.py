from typing import Any

from sqlalchemy import Result, insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.base.repository import ConcreteTable, SQLAlchemyRepository
from backend.core.database import session_manager
from backend.files.models import File, OrderFile
from backend.files.schemas import FileSchemaIn, FileSchemaOut


__all__ = ("FileRepository",)


class FileRepository(SQLAlchemyRepository):
    """
    Репозиторий для работы с таблицей файлов (File) и связующей таблицей (OrderFile).

    Атрибуты:
        model (Type[ConcreteTable]): Модель таблицы файлов (File).
        link_model (Type[ConcreteTable]): Модель связующей таблицы (OrderFile).
        response_schema (Type[FileSchemaOut]): Схема для преобразования данных в ответ.
        load_joined_models (bool): Флаг для загрузки связанных моделей (по умолчанию False).
    """

    model = File
    link_model = OrderFile
    response_schema = FileSchemaOut
    request_schema = FileSchemaIn
    load_joined_models = False

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def add_link(
        self, session: AsyncSession, data: dict[str, Any]
    ) -> ConcreteTable:
        """
        Добавляет связь между файлом и заказом в связующую таблицу (OrderFile).

        :param session: Асинхронная сессия SQLAlchemy.
        :param data: Данные для создания связи (содержит order_id и file_id).
        :return: Объект созданной связи или исключение, если произошла ошибка.
        """
        try:
            # Вызов метода add из родительского класса для добавления файла (если требуется)
            super().add(data=data)

            # Добавление записи в связующую таблицу
            result: Result = await session.execute(
                insert(self.link_model).values(**data).returning(self.link_model)
            )
            await session.flush()
            return result.scalars().one_or_none()
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком
