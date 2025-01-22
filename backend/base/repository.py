import importlib
from abc import ABC, abstractmethod
from typing import (
    Any,
    AsyncGenerator,
    Dict,
    Generic,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
)

from fastapi_filter.contrib.sqlalchemy import Filter
from sqlalchemy import (
    Insert,
    Result,
    Select,
    Update,
    asc,
    delete,
    desc,
    func,
    inspect,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy_continuum import version_class

from backend.base.models import BaseModel
from backend.core.database import session_manager
from backend.core.errors import DatabaseError, NotFoundError, handle_db_errors


# Тип для указания конкретной модели таблицы
ConcreteTable = TypeVar("ConcreteTable", bound=BaseModel)


class AbstractRepository(ABC):
    """
    Абстрактный базовый класс для репозиториев.
    Определяет интерфейс для работы с базой данных.
    """

    @abstractmethod
    async def get(self, session: AsyncSession, key: str, value: Any) -> ConcreteTable:
        """Получить объект по ключу и значению."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_params(
        self, session: AsyncSession, filter: Filter
    ) -> List[ConcreteTable]:
        """Получить объекты по параметрам фильтра."""
        raise NotImplementedError

    @abstractmethod
    async def count(self, session: AsyncSession) -> int:
        """Получить количество объектов в таблице."""
        raise NotImplementedError

    @abstractmethod
    async def first_or_last(
        self, session: AsyncSession, by: str = "id", order: str = "asc"
    ) -> ConcreteTable:
        """Получить первый или последний объект в таблице, отсортированный по указанному полю."""
        raise NotImplementedError

    @abstractmethod
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> ConcreteTable:
        """Добавить новый объект в таблицу."""
        raise NotImplementedError

    @abstractmethod
    async def update(
        self, session: AsyncSession, key: str, value: Any, data: dict[str, Any]
    ) -> ConcreteTable:
        """Обновить объект в таблице."""
        raise NotImplementedError

    @abstractmethod
    async def all(self, session: AsyncSession) -> List[ConcreteTable]:
        """Получить все объекты из таблицы."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, session: AsyncSession, key: str, value: Any) -> None:
        """Удалить объект из таблицы по ключу и значению."""
        raise NotImplementedError

    @abstractmethod
    async def get_all_versions(
        self, session: AsyncSession, object_id: int
    ) -> List[ConcreteTable]:
        """Получить все версии объекта по его id."""
        raise NotImplementedError

    @abstractmethod
    async def get_latest_version(
        self, session: AsyncSession, object_id: int
    ) -> Optional[ConcreteTable]:
        """Получить последнюю версию объекта."""
        raise NotImplementedError

    @abstractmethod
    async def restore_to_version(
        self, session: AsyncSession, object_id: int, transaction_id: int
    ) -> ConcreteTable:
        """Восстановить объект до указанной версии."""
        raise NotImplementedError


class SQLAlchemyRepository(AbstractRepository, Generic[ConcreteTable]):
    """
    Базовый класс для взаимодействия с БД с использованием SQLAlchemy.
    Реализует методы для работы с конкретной моделью таблицы.
    """

    def __init__(
        self,
        model: Type[ConcreteTable] = None,  # Конкретная модель таблицы
        load_joined_models: bool = False,  # Флаг для загрузки связанных моделей
    ):
        self.model = model
        self.load_joined_models = load_joined_models

    async def _prepare_and_save_object(
        self,
        session: AsyncSession,
        data: dict[str, Any],
        existing_object: Optional[ConcreteTable] = None,
    ) -> ConcreteTable:
        """
        Обрабатывает данные и сохраняет объект в базе данных.
        Если передан existing_object, обновляет его. Иначе создает новый объект.

        :param session: Асинхронная сессия SQLAlchemy.
        :param data: Данные для создания или обновления объекта.
        :param existing_object: Существующий объект для обновления (опционально).
        :return: Созданный или обновленный объект.
        """
        unsecret_data = await self.model.get_value_from_secret_str(
            data
        )  # Обрабатываем данные

        if existing_object:
            # Обновляем существующий объект
            for field, new_value in unsecret_data.items():
                if new_value is not None:
                    setattr(existing_object, field, new_value)
            obj = existing_object
        else:
            # Создаем новый объект
            obj = self.model(**unsecret_data)

        session.add(obj)  # Добавляем объект в сессию
        await session.flush()  # Фиксируем изменения
        await self._refresh_with_relationships(session, obj)  # Обновляем связи
        return obj

    async def _refresh_with_relationships(
        self, session: AsyncSession, obj: ConcreteTable
    ) -> None:
        """
        Обновляет объект и загружает все его связи.
        Используется для обновления объекта после добавления или обновления.

        :param session: Асинхронная сессия SQLAlchemy.
        :param obj: Объект для обновления.
        """
        mapper = inspect(obj.__class__)
        relationships = [rel.key for rel in mapper.relationships]  # Получаем все связи
        await session.refresh(obj, attribute_names=relationships)  # Обновляем объект

    async def _get_loaded_object(
        self,
        session: AsyncSession,
        query_or_object: Union[Select, ConcreteTable],
        is_return_list: bool = False,
    ) -> Optional[ConcreteTable] | List[ConcreteTable]:
        """
        Выполняет запрос или подгружает связи для объекта.
        Если передан запрос (Select), выполняет его и возвращает результат.
        Если передан объект, загружает его связи (если включено).

        :param session: Асинхронная сессия SQLAlchemy.
        :param query_or_object: Запрос или объект для загрузки.
        :param is_return_list: Флаг, указывающий, нужно ли возвращать список объектов.
        :return: Объект или список объектов.
        """
        mapper = inspect(self.model)
        relationships = [rel.key for rel in mapper.relationships]  # Получаем все связи

        if isinstance(query_or_object, Select):
            # Если передан запрос, добавляем опции для загрузки связанных моделей
            if self.load_joined_models:
                options = [
                    selectinload(getattr(self.model, key)) for key in relationships
                ]
                query_or_object = query_or_object.options(*options)

            result: Result = await session.execute(query_or_object)  # Выполняем запрос
            return (
                result.scalars().all()  # Возвращаем список объектов
                if is_return_list
                else result.scalar_one_or_none()  # Возвращаем один объект
            )

        elif self.load_joined_models:
            # Если передан объект и нужно загрузить связи
            if query_or_object not in session:
                session.add(query_or_object)
                await session.flush()

            # Создаем запрос для загрузки объекта с его связями
            query = (
                select(self.model)
                .where(self.model.id == query_or_object.id)
                .options(
                    *[selectinload(getattr(self.model, key)) for key in relationships]
                )
            )
            result: Result = await session.execute(query)
            return result.scalar_one_or_none()

        return query_or_object  # Возвращаем объект без изменений

    async def _execute_stmt(
        self, session: AsyncSession, stmt: Insert | Update
    ) -> Optional[ConcreteTable]:
        """
        Выполняет SQL-запрос (INSERT или UPDATE) и возвращает созданный или обновленный объект.

        :param session: Асинхронная сессия SQLAlchemy.
        :param stmt: SQL-запрос для выполнения.
        :return: Созданный или обновленный объект.
        """
        await session.flush()
        result = await session.execute(stmt)
        if not result:
            raise DatabaseError(message="Failed to create/update record")

        primary_key = result.unique().scalar_one_or_none().id  # Получаем ID объекта
        query = select(self.model).where(
            self.model.id == primary_key
        )  # Запрос для получения объекта
        return await self._get_loaded_object(session, query)

    @handle_db_errors
    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get(
        self, session: AsyncSession, key: str, value: Any
    ) -> Optional[ConcreteTable]:
        """
        Получить объект по ключу и значению.

        :param session: Асинхронная сессия SQLAlchemy.
        :param key: Название поля для фильтрации.
        :param value: Значение поля для фильтрации.
        :return: Найденный объект или None.
        """
        query = select(self.model).where(getattr(self.model, key) == value)
        return await self._get_loaded_object(session, query)

    @handle_db_errors
    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_by_params(
        self, session: AsyncSession, filter: Filter
    ) -> AsyncGenerator[ConcreteTable, None]:
        """
        Получить объекты по параметрам фильтра.

        :param session: Асинхронная сессия SQLAlchemy.
        :param filter: Фильтр для запроса.
        :return: Асинхронный генератор объектов.
        """
        query = filter.filter(select(self.model))
        return await self._get_loaded_object(session, query, is_return_list=True)

    @handle_db_errors
    @session_manager.connection(isolation_level="READ COMMITTED")
    async def count(self, session: AsyncSession) -> int:
        """
        Получить количество объектов в таблице.

        :param session: Асинхронная сессия SQLAlchemy.
        :return: Количество объектов.
        """
        result: Result = await session.execute(func.count(self.model.id))
        return result.scalar()

    @handle_db_errors
    @session_manager.connection(isolation_level="READ COMMITTED")
    async def first_or_last(
        self, session: AsyncSession, by: str = "id", order: str = "asc"
    ) -> Optional[ConcreteTable]:
        """
        Получить первый или последний объект в таблице, отсортированный по указанному полю.

        :param session: Асинхронная сессия SQLAlchemy.
        :param by: Поле для сортировки.
        :param order: Порядок сортировки ("asc" или "desc").
        :return: Первый или последний объект.
        """
        order_by = (
            asc(by) if order == "asc" else desc(by)
        )  # Определяем порядок сортировки
        query = select(self.model).order_by(order_by).limit(1)  # Создаем запрос
        return await self._get_loaded_object(session, query)

    @handle_db_errors
    @session_manager.connection(isolation_level="READ COMMITTED", commit=True)
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> ConcreteTable:
        """
        Добавить новый объект в таблицу.

        :param session: Асинхронная сессия SQLAlchemy.
        :param data: Данные для создания объекта.
        :return: Созданный объект.
        """
        return await self._prepare_and_save_object(session, data)

    @handle_db_errors
    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def update(
        self, session: AsyncSession, key: str, value: Any, data: dict[str, Any]
    ) -> ConcreteTable:
        """
        Обновить объект в таблице.

        :param session: Асинхронная сессия SQLAlchemy.
        :param key: Название поля для поиска объекта.
        :param value: Значение поля для поиска объекта.
        :param data: Данные для обновления объекта.
        :return: Обновленный объект.
        """
        existing_object = await self.get(
            key=key, value=value
        )  # Получаем существующий объект
        if not existing_object:
            raise NotFoundError(message="Object not found")

        return await self._prepare_and_save_object(session, data, existing_object)

    @handle_db_errors
    @session_manager.connection(isolation_level="READ COMMITTED")
    async def all(self, session: AsyncSession) -> List[ConcreteTable]:
        """
        Получить все объекты из таблицы.

        :param session: Асинхронная сессия SQLAlchemy.
        :return: Список всех объектов.
        """
        query = select(self.model)
        return await self._get_loaded_object(session, query, is_return_list=True)

    @handle_db_errors
    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def delete(self, session: AsyncSession, key: str, value: Any) -> None:
        """
        Удалить объект из таблицы по ключу и значению.

        :param session: Асинхронная сессия SQLAlchemy.
        :param key: Название поля для поиска объекта.
        :param value: Значение поля для поиска объекта.
        """
        result = await session.execute(
            delete(self.model)
            .where(getattr(self.model, key) == value)
            .returning(self.model.id)
        )
        await session.flush()
        return result.scalars().one()

    @handle_db_errors
    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_all_versions(
        self, session: AsyncSession, object_id: int
    ) -> List[Dict[str, Any]]:
        """
        Получить все версии объекта по его id, включая id транзакции.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :return: Список версий объекта.
        """
        VersionModel = version_class(self.model)  # Получаем модель версий
        result = await session.execute(
            select(VersionModel)
            .filter(VersionModel.id == object_id)
            .order_by(VersionModel.transaction_id)
        )
        versions = result.scalars().all()
        return [version for version in versions]

    @handle_db_errors
    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_latest_version(
        self, session: AsyncSession, object_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Получить последнюю версию объекта, включая id транзакции.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :return: Последняя версия объекта.
        """
        VersionModel = version_class(self.model)  # Получаем модель версий
        result = await session.execute(
            select(VersionModel)
            .filter(VersionModel.id == object_id)
            .order_by(VersionModel.transaction_id.desc())
            .limit(1)
        )
        version = result.scalars().first()
        return version

    @handle_db_errors
    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def restore_to_version(
        self, session: AsyncSession, object_id: int, transaction_id: int
    ) -> Dict[str, Any]:
        """
        Восстановить объект до указанной версии и вернуть информацию о транзакции.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :param transaction_id: ID транзакции, до которой нужно восстановить объект.
        :return: Информация о восстановленной версии.
        """
        VersionModel = version_class(self.model)  # Получаем модель версий
        target_version = await session.execute(
            select(VersionModel).filter(
                VersionModel.id == object_id,
                VersionModel.transaction_id == transaction_id,
            )
        )
        target_version = target_version.scalars().first()

        if not target_version:
            raise NotFoundError(
                message=f"Version with transaction_id={transaction_id} not found"
            )

        parent_obj = await self.get(
            key="id", value=object_id
        )  # Получаем родительский объект
        if not parent_obj:
            raise NotFoundError(message=f"Object with id={object_id} not found")

        # Восстанавливаем атрибуты объекта до указанной версии
        for attr in target_version.__table__.columns.keys():
            if attr not in ["id", "transaction_id", "operation_type"]:
                setattr(parent_obj, attr, getattr(target_version, attr))

        await session.commit()  # Фиксируем изменения

        return {
            "transaction_id": transaction_id,
            "data": parent_obj,
        }


async def get_repository_for_model(
    model: Type[BaseModel],
) -> Type[SQLAlchemyRepository[ConcreteTable]]:
    """
    Возвращает класс репозитория для указанной модели.

    """
    repository_name = f"{model.__name__}Repository"  # Формируем имя репозитория

    try:
        # Импортируем модуль репозитория для указанной модели
        repository_module = importlib.import_module(
            f"backend.{model.__tablename__}.repository"
        )
        repository_class = getattr(
            repository_module, repository_name
        )  # Получаем класс репозитория
        return repository_class
    except (ImportError, AttributeError) as exc:
        raise ValueError(
            f"Репозиторий для модели {model.__name__} не найден: {str(exc)}"
        )
