import importlib
from abc import ABC, abstractmethod
from typing import (
    Any,
    AsyncGenerator,
    Coroutine,
    Generic,
    List,
    Optional,
    Type,
    TypeVar,
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
    insert,
    inspect,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.base.models import BaseModel
from backend.core.database import session_manager
from backend.core.errors import UnprocessableError


ConcreteTable = TypeVar("ConcreteTable", bound=BaseModel)


class AbstractRepository(ABC):
    """Абстрактный базовый класс для репозиториев."""

    @abstractmethod
    async def get(self, session: AsyncSession, key: str, value: Any) -> ConcreteTable:
        """Получить объект по ключу и значению."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_params(
        self, session: AsyncSession, filter: Filter
    ) -> AsyncGenerator[ConcreteTable, None]:
        """Получить объекты по параметрам фильтра."""
        raise NotImplementedError

    @abstractmethod
    async def count(self, session: AsyncSession) -> int:
        """Получить количество объектов в таблице."""
        raise NotImplementedError

    @abstractmethod
    async def first(self, session: AsyncSession, by: str = "id") -> ConcreteTable:
        """Получить первый объект в таблице, отсортированный по указанному полю."""
        raise NotImplementedError

    @abstractmethod
    async def last(self, session: AsyncSession, by: str = "id") -> ConcreteTable:
        """Получить последний объект в таблице, отсортированный по указанному полю."""
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
    async def all(
        self, session: AsyncSession
    ) -> Coroutine[Any, Any, List[ConcreteTable]]:
        """Получить все объекты из таблицы."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, session: AsyncSession, key: str, value: Any) -> None:
        """Удалить объект из таблицы по ключу и значению."""
        raise NotImplementedError


class SQLAlchemyRepository(AbstractRepository, Generic[ConcreteTable]):
    """Базовый класс для взаимодействия с БД с использованием SQLAlchemy."""

    model: Type[ConcreteTable] = None
    load_joined_models: bool = False

    async def _get_loaded_object(
        self, session: AsyncSession, query: Select, is_return_list: bool = False
    ) -> Optional[ConcreteTable | List[ConcreteTable]]:
        """
        Выполняет запрос и возвращает объект или список объектов.

        :param session: Асинхронная сессия SQLAlchemy.
        :param query: Запрос к базе данных.
        :param is_return_list: Флаг, указывающий, нужно ли возвращать список объектов.
        :return: Объект или список объектов, либо None, если объект не найден.
        """
        result: Result = await session.execute(query)
        if result and self.load_joined_models:
            mapper = inspect(self.model)
            relationships = [rel.key for rel in mapper.relationships]
            options = [joinedload(getattr(self.model, key)) for key in relationships]
            query_with_options = query.options(*options)
            result = await session.execute(query_with_options)

        return (
            result.unique().scalars().all()
            if is_return_list
            else result.unique().scalar_one_or_none()
        )

    async def _execute_stmt(
        self, session: AsyncSession, stmt: Insert | Update
    ) -> ConcreteTable:
        """
        Выполняет SQL-запрос и возвращает созданный или обновленный объект.

        :param session: Асинхронная сессия SQLAlchemy.
        :param stmt: SQL-запрос (INSERT или UPDATE).
        :return: Созданный или обновленный объект.
        :raises ValueError: Если запрос не был выполнен успешно.
        """
        await session.flush()
        result = await session.execute(stmt)

        if not result:
            raise ValueError("Failed to create/update record")

        primary_key = result.unique().scalar_one_or_none().id
        query = select(self.model).where(self.model.id == primary_key)
        return await self._get_loaded_object(session, query)

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get(
        self, session: AsyncSession, key: str, value: Any
    ) -> Optional[ConcreteTable]:
        """
        Получить объект по ключу и значению.

        :param session: Асинхронная сессия SQLAlchemy.
        :param key: Название поля.
        :param value: Значение поля.
        :return: Объект, если найден, иначе None.
        """
        query = select(self.model).where(getattr(self.model, key) == value)
        return await self._get_loaded_object(session, query)

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

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def count(self, session: AsyncSession) -> int:
        """
        Получить количество объектов в таблице.

        :param session: Асинхронная сессия SQLAlchemy.
        :return: Количество объектов.
        :raises UnprocessableError: Если тип результата не является целым числом.
        """
        result: Result = await session.execute(func.count(self.model.id))
        value = result.scalar()
        if not isinstance(value, int):
            raise UnprocessableError(message="Error output type")
        return value

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def first(
        self, session: AsyncSession, by: str = "id"
    ) -> Optional[ConcreteTable]:
        """
        Получить первый объект в таблице, отсортированный по указанному полю.

        :param session: Асинхронная сессия SQLAlchemy.
        :param by: Поле для сортировки.
        :return: Первый объект, если найден, иначе None.
        """
        query = select(self.model).order_by(asc(by)).limit(1)
        return await self._get_loaded_object(session, query)

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def last(
        self, session: AsyncSession, by: str = "id"
    ) -> Optional[ConcreteTable]:
        """
        Получить последний объект в таблице, отсортированный по указанному полю.

        :param session: Асинхронная сессия SQLAlchemy.
        :param by: Поле для сортировки.
        :return: Последний объект, если найден, иначе None.
        """
        query = select(self.model).order_by(desc(by)).limit(1)
        return await self._get_loaded_object(session, query)

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> ConcreteTable:
        """
        Добавить новый объект в таблицу.

        :param session: Асинхронная сессия SQLAlchemy.
        :param data: Данные для создания объекта.
        :return: Созданный объект.
        :raises Exception: Если произошла ошибка при добавлении объекта.
        """
        try:
            unsecret_data = await self.model.get_value_from_secret_str(data)
            stmt = insert(self.model).values(**unsecret_data).returning(self.model)
            return await self._execute_stmt(session, stmt)
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def add_many(
        self, session: AsyncSession, data_list: list[dict[str, Any]]
    ) -> List[ConcreteTable]:
        """
        Добавить несколько объектов в таблицу.

        :param session: Асинхронная сессия SQLAlchemy.
        :param data_list: Список данных для создания объектов.
        :return: Список созданных объектов.
        :raises Exception: Если произошла ошибка при добавлении объектов.
        """
        try:
            results = []
            for data in data_list:
                result = await self.add(session, data)
                results.append(result)
            return results
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def update(
        self, session: AsyncSession, key: str, value: Any, data: dict[str, Any]
    ) -> ConcreteTable:
        """
        Обновить объект в таблице.

        :param session: Асинхронная сессия SQLAlchemy.
        :param key: Название поля.
        :param value: Значение поля.
        :param data: Данные для обновления объекта.
        :return: Обновленный объект.
        :raises Exception: Если произошла ошибка при обновлении объекта.
        """
        try:
            unsecret_data = await self.model.get_value_from_secret_str(data)
            stmt = (
                update(self.model)
                .where(getattr(self.model, key) == value)
                .values(**unsecret_data)
                .returning(self.model)
            )
            return await self._execute_stmt(session, stmt)
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def all(
        self, session: AsyncSession
    ) -> Coroutine[Any, Any, List[ConcreteTable]]:
        """
        Получить все объекты из таблицы.

        :param session: Асинхронная сессия SQLAlchemy.
        :return: Список всех объектов.
        """
        query = select(self.model)
        return await self._get_loaded_object(session, query, is_return_list=True)

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def delete(self, session: AsyncSession, key: str, value: Any) -> None:
        """
        Удалить объект из таблицы по ключу и значению.

        :param session: Асинхронная сессия SQLAlchemy.
        :param key: Название поля.
        :param value: Значение поля.
        :return: None.
        :raises Exception: Если произошла ошибка при удалении объекта.
        """
        try:
            result = await session.execute(
                delete(self.model)
                .where(getattr(self.model, key) == value)
                .returning(self.model.id)
            )
            await session.flush()
            return result.scalars().one()
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком


async def get_repository_for_model(
    model: Type[BaseModel],
) -> Type[SQLAlchemyRepository]:
    """
    Возвращает класс репозитория для указанной модели.

    Аргументы:
        model (Type[BaseModel]): Класс модели.

    Возвращает:
        Type[SQLAlchemyRepository]: Класс репозитория, связанный с моделью.

    Исключения:
        ValueError: Если репозиторий для модели не найден.
    """
    repository_name = f"{model.__name__}Repository"

    # Импортируем модуль репозиториев
    try:
        repository_module = importlib.import_module(
            f"backend.{model.__tablename__}.repository"
        )
    except ImportError:
        raise ValueError(
            f"Модуль репозиториев для таблицы {model.__tablename__} не найден."
        )
    # Получаем класс репозитория
    try:
        repository_class = getattr(repository_module, repository_name)
    except AttributeError:
        raise ValueError(
            f"Репозиторий {repository_name} для таблицы {model.__tablename__} не найден."
        )

    return repository_class
