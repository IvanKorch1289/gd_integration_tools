import importlib
from abc import ABC, abstractmethod
from typing import (
    Any,
    AsyncGenerator,
    Coroutine,
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
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy_continuum import version_class

from backend.base.models import BaseModel
from backend.core.database import session_manager
from backend.core.errors import DatabaseError, NotFoundError


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
    ) -> List[ConcreteTable]:
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
    async def all(self, session: AsyncSession) -> List[ConcreteTable]:  # Упрощено
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
    ) -> Optional[ConcreteTable]:
        """Восстановить объект до указанной версии."""
        raise NotImplementedError

    @abstractmethod
    async def get_changes(
        self, session: AsyncSession, object_id: int
    ) -> List[Dict[str, Any]]:
        """Получить список изменений атрибутов объекта."""
        raise NotImplementedError


class SQLAlchemyRepository(AbstractRepository, Generic[ConcreteTable]):
    """Базовый класс для взаимодействия с БД с использованием SQLAlchemy."""

    model: Type[ConcreteTable] = None
    load_joined_models: bool = False

    async def _get_loaded_object(
        self,
        session: AsyncSession,
        query_or_object: Union[select, ConcreteTable],
        is_return_list: bool = False,
    ) -> Optional[ConcreteTable] | List[ConcreteTable]:
        """
        Выполняет запрос или подгружает связи для объекта.

        :param session: Асинхронная сессия SQLAlchemy.
        :param query_or_object: Запрос к базе данных или объект модели.
        :param is_return_list: Флаг, указывающий, нужно ли возвращать список объектов.
        :return: Объект, если is_return_list=False, иначе список объектов.
                Возвращает None, если объект не найден.
        """
        try:
            # Получаем маппер модели и список отношений
            mapper = inspect(self.model)
            relationships = [rel.key for rel in mapper.relationships]

            if isinstance(query_or_object, Select):
                # Если передан запрос, выполняем его
                if self.load_joined_models:
                    # Подгружаем связи, если требуется
                    options = [
                        selectinload(getattr(self.model, key)) for key in relationships
                    ]
                    query_or_object = query_or_object.options(*options)

                result: Result = await session.execute(query_or_object)
                if is_return_list:
                    return result.scalars().all()  # Возвращаем список объектов
                return result.scalar_one_or_none()  # Возвращаем один объект или None

            else:
                # Если передан объект, подгружаем его связи
                if self.load_joined_models:
                    # Убедимся, что объект привязан к сессии
                    if query_or_object not in session:
                        session.add(query_or_object)
                        await session.flush()

                    # Загружаем связанные объекты с помощью selectinload
                    query = (
                        select(self.model)
                        .where(self.model.id == query_or_object.id)
                        .options(
                            *[
                                selectinload(getattr(self.model, key))
                                for key in relationships
                            ]
                        )
                    )
                    result: Result = await session.execute(query)
                    query_or_object = result.scalar_one_or_none()

            return query_or_object

        except Exception as exc:
            raise DatabaseError(
                message=f"Failed to load object or its relationships: {str(exc)}"
            )

    async def _execute_stmt(
        self, session: AsyncSession, stmt: Insert | Update
    ) -> Optional[ConcreteTable]:
        """
        Выполняет SQL-запрос и возвращает созданный или обновленный объект.

        :param session: Асинхронная сессия SQLAlchemy.
        :param stmt: SQL-запрос (INSERT или UPDATE).
        :return: Созданный или обновленный объект, либо None, если запрос не был выполнен успешно.
        :raises ValueError: Если запрос не был выполнен успешно.
        """
        try:
            await session.flush()
            result = await session.execute(stmt)

            if not result:
                raise DatabaseError(message="Failed to create/update record")

            primary_key = result.unique().scalar_one_or_none().id
            query = select(self.model).where(self.model.id == primary_key)
            return await self._get_loaded_object(session, query)
        except Exception as exc:
            raise DatabaseError(message=str(exc))

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
        try:
            query = select(self.model).where(getattr(self.model, key) == value)
            return await self._get_loaded_object(session, query)
        except Exception as exc:
            raise DatabaseError(message=str(exc))

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
        try:
            query = filter.filter(select(self.model))
            return await self._get_loaded_object(session, query, is_return_list=True)
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def count(self, session: AsyncSession) -> int:
        """
        Получить количество объектов в таблице.

        :param session: Асинхронная сессия SQLAlchemy.
        :return: Количество объектов.
        :raises UnprocessableError: Если тип результата не является целым числом.
        """
        try:
            result: Result = await session.execute(func.count(self.model.id))
            return result.scalar()
        except Exception as exc:
            raise DatabaseError(message=str(exc))

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
        try:
            query = select(self.model).order_by(asc(by)).limit(1)
            return await self._get_loaded_object(session, query)
        except Exception as exc:
            raise DatabaseError(message=str(exc))

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
        try:
            query = select(self.model).order_by(desc(by)).limit(1)
            return await self._get_loaded_object(session, query)
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="READ COMMITTED", commit=True)
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> ConcreteTable:
        """
        Добавляет новый объект в репозиторий и возвращает его в виде схемы.

        :param session: Асинхронная сессия SQLAlchemy.
        :param data: Данные для создания объекта.
        :return: Созданный объект.
        :raises DatabaseError: Если произошла ошибка при создании объекта.
        """
        try:
            # Преобразуем данные, если требуется
            unsecret_data = await self.model.get_value_from_secret_str(data)

            # Создаем новый объект
            new_object = self.model(**unsecret_data)

            # Добавляем объект в сессию
            session.add(new_object)
            await session.flush()

            # Загружаем связанные объекты через универсальный метод
            loaded_object = await self._get_loaded_object(session, new_object)

            if not loaded_object:
                raise DatabaseError(message="Failed to load created object")

            return loaded_object
        except Exception as exc:
            raise DatabaseError(message=str(exc))

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
        except Exception as exc:
            raise DatabaseError(message=str(exc))

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
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def all(
        self, session: AsyncSession
    ) -> Coroutine[Any, Any, List[ConcreteTable]]:
        """
        Получить все объекты из таблицы.

        :param session: Асинхронная сессия SQLAlchemy.
        :return: Список всех объектов.
        """
        try:
            query = select(self.model)
            return await self._get_loaded_object(session, query, is_return_list=True)
        except Exception as exc:
            raise DatabaseError(message=str(exc))

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
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_all_versions(
        self, session: AsyncSession, object_id: int
    ) -> List[ConcreteTable]:
        """
        Получить все версии объекта по его id.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :return: Список всех версий объекта.
        """
        try:
            VersionModel = version_class(self.model)
            result = await session.execute(
                select(VersionModel)
                .filter(VersionModel.id == object_id)
                .order_by(VersionModel.transaction_id)
            )
            return result.scalars().all()
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_latest_version(
        self, session: AsyncSession, object_id: int
    ) -> Optional[ConcreteTable]:
        """
        Получить последнюю версию объекта.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :return: Последняя версия объекта, если найдена, иначе None.
        """
        try:
            VersionModel = version_class(self.model)
            result = await session.execute(
                select(VersionModel)
                .filter(VersionModel.id == object_id)
                .order_by(VersionModel.transaction_id.desc())
                .limit(1)
            )
            return result.scalars().first()
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def restore_to_version(
        self, session: AsyncSession, object_id: int, transaction_id: int
    ) -> ConcreteTable:
        """
        Восстановить объект до указанной версии.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :param transaction_id: ID транзакции, до которой нужно восстановить объект.
        :return: Восстановленный объект.
        :raises ValueError: Если версия или объект не найдены.
        """
        try:
            VersionModel = version_class(self.model)
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

            parent_obj = await self.get(session, "id", object_id)
            if not parent_obj:
                raise NotFoundError(message=f"Object with id={object_id} not found")

            for attr in target_version.__table__.columns.keys():
                if attr not in ["id", "transaction_id", "operation_type"]:
                    setattr(parent_obj, attr, getattr(target_version, attr))

            await session.commit()
            return parent_obj
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_changes(
        self, session: AsyncSession, object_id: int
    ) -> List[Dict[str, Any]]:
        """
        Получить список изменений атрибутов объекта.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :return: Список изменений атрибутов объекта.
        """
        try:
            versions = await self.get_all_versions(object_id=object_id)

            if not versions:
                return None

            changes = []
            for i in range(1, len(versions)):
                prev_version = versions[i - 1]
                current_version = versions[i]

                diff = {}
                for attr in current_version.__table__.columns.keys():
                    if getattr(current_version, attr) != getattr(prev_version, attr):
                        diff[attr] = {
                            "old": getattr(prev_version, attr),
                            "new": getattr(current_version, attr),
                        }

                if diff:
                    changes.append(
                        {
                            "transaction_id": current_version.transaction_id,
                            "changes": diff,
                        }
                    )

            return changes
        except Exception as exc:
            raise DatabaseError(message=str(exc))


async def get_repository_for_model(
    model: Type[BaseModel],
) -> Type[SQLAlchemyRepository[ConcreteTable]]:
    """
    Возвращает класс репозитория для указанной модели.

    Аргументы:
        model (Type[BaseModel]): Класс модели.

    Возвращает:
        Type[SQLAlchemyRepository[ConcreteTable]]: Класс репозитория, связанный с моделью.

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
