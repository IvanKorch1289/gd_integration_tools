import importlib
from abc import ABC, abstractmethod
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union

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

    class HelperMethods:
        """
        Вспомогательные методы для работы с базой данных.
        """

        def __init__(
            self, model: Type[ConcreteTable], load_joined_models: bool = False
        ):
            self.model = model
            self.load_joined_models = load_joined_models

        async def _prepare_and_save_object(
            self,
            session: AsyncSession,
            data: dict[str, Any],
            existing_object: Optional[ConcreteTable] = None,
            ignore_none: bool = True,
        ) -> ConcreteTable:
            """
            Обрабатывает данные и сохраняет объект в базе данных.
            """
            unsecret_data = await self.model.get_value_from_secret_str(data)

            if existing_object:
                for field, new_value in unsecret_data.items():
                    if not ignore_none or new_value is not None:
                        setattr(existing_object, field, new_value)
                obj = existing_object
            else:
                obj = self.model(**unsecret_data)

            session.add(obj)
            await session.flush()
            await self._refresh_with_relationships(session, obj)
            return obj

        async def _refresh_with_relationships(
            self, session: AsyncSession, obj: ConcreteTable
        ) -> None:
            """
            Обновляет объект и загружает все его связи.
            """
            mapper = inspect(obj.__class__)
            relationships = [
                rel.key
                for rel in mapper.relationships
                if rel.key
                not in getattr(obj.__class__, "EXCLUDED_RELATIONSHIPS", set())
                and rel.key != "versions"
            ]
            await session.refresh(obj, attribute_names=relationships)

        async def _get_loaded_object(
            self,
            session: AsyncSession,
            query_or_object: Union[Select, ConcreteTable],
            is_return_list: bool = False,
        ) -> Optional[ConcreteTable] | List[ConcreteTable]:
            """
            Выполняет запрос или подгружает связи для объекта.

            :param session: Асинхронная сессия SQLAlchemy.
            :param query_or_object: Запрос или объект для загрузки.
            :param is_return_list: Если True, возвращает список объектов. Иначе — один объект или None.
            :return: Объект, список объектов или пустой список/словарь, если данные не найдены.
            """
            if isinstance(query_or_object, Select):
                if self.load_joined_models:
                    query_or_object = query_or_object.options(
                        *self._get_selectinload_options()
                    )

                result: Result = await session.execute(query_or_object)

                if is_return_list:
                    objects = result.scalars().all()
                    return (
                        objects if objects else []
                    )  # Возвращаем пустой список, если данных нет
                else:
                    return (
                        result.scalars().first() or {}
                    )  # Возвращаем пустой словарь, если объект не найден

            elif self.load_joined_models:
                if query_or_object not in session:
                    session.add(query_or_object)
                    await session.flush()

                query = (
                    select(self.model)
                    .where(self.model.id == query_or_object.id)
                    .options(*self._get_selectinload_options())
                )
                result: Result = await session.execute(query)
                return (
                    result.scalars().first() or {}
                )  # Возвращаем пустой словарь, если объект не найден

            return query_or_object

        def _get_selectinload_options(self) -> list:
            """
            Формирует список опций для загрузки связанных моделей.
            """
            mapper = inspect(self.model)
            relationships = [rel.key for rel in mapper.relationships]

            return [
                selectinload(getattr(self.model, key))
                for key in relationships
                if key not in getattr(self.model, "EXCLUDED_RELATIONSHIPS", set())
                and key != "versions"
            ]

        async def _execute_stmt(
            self, session: AsyncSession, stmt: Insert | Update
        ) -> Optional[ConcreteTable]:
            """
            Выполняет SQL-запрос (INSERT или UPDATE) и возвращает созданный или обновленный объект.
            """
            await session.flush()
            result = await session.execute(stmt)
            if not result:
                raise DatabaseError(message="Failed to create/update record")

            primary_key = result.unique().scalar_one_or_none().id
            query = select(self.model).where(self.model.id == primary_key)
            return await self._get_loaded_object(session, query)

        async def _get_versions_query(
            self,
            session: AsyncSession,
            object_id: int,
            order: str = "asc",
            limit: Optional[int] = None,
        ) -> List[Dict[str, Any]]:
            """
            Общий метод для получения версий объекта.
            """
            VersionModel = version_class(self.model)
            query = select(VersionModel).filter(VersionModel.id == object_id)

            if order == "asc":
                query = query.order_by(VersionModel.transaction_id)
            elif order == "desc":
                query = query.order_by(VersionModel.transaction_id.desc())

            if limit:
                query = query.limit(limit)

            result = await session.execute(query)
            return result.scalars().all()

    def __init__(
        self,
        model: Type[ConcreteTable] = None,
        load_joined_models: bool = False,
    ):
        self.model = model
        self.load_joined_models = load_joined_models
        self.helper = self.HelperMethods(model, load_joined_models)

    @handle_db_errors
    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get(
        self,
        session: AsyncSession,
        key: Optional[str] = None,
        value: Optional[Any] = None,
        filter: Optional[Filter] = None,
    ) -> Optional[ConcreteTable] | List[ConcreteTable]:
        """
        Получить объект по ключу и значению или по фильтру.

        :param session: Асинхронная сессия SQLAlchemy.
        :param key: Название поля для фильтрации (опционально).
        :param value: Значение поля для фильтрации (опционально).
        :param filter: Фильтр для запроса (опционально).
        :param is_return_list: Если True, возвращает список объектов. Иначе — один объект или None.
        :return: Найденный объект, список объектов или None.
        """
        is_return_list = False

        if filter:
            query = filter.filter(select(self.model))
            is_return_list = True
        elif key and value:
            query = select(self.model).where(getattr(self.model, key) == value)
        else:
            query = select(self.model)
            is_return_list = True

        return await self.helper._get_loaded_object(
            session, query, is_return_list=is_return_list
        )

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
        return await self.helper._get_loaded_object(session, query)

    @handle_db_errors
    @session_manager.connection(isolation_level="READ COMMITTED", commit=True)
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> ConcreteTable:
        """
        Добавить новый объект в таблицу.

        :param session: Асинхронная сессия SQLAlchemy.
        :param data: Данные для создания объекта.
        :return: Созданный объект.
        """
        return await self.helper._prepare_and_save_object(session, data)

    @handle_db_errors
    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def update(
        self,
        session: AsyncSession,
        key: str,
        value: Any,
        data: dict[str, Any],
        ignore_none: bool = True,  # По умолчанию игнорируем пустые значения
    ) -> ConcreteTable:
        """
        Обновить объект в таблице.

        :param session: Асинхронная сессия SQLAlchemy.
        :param key: Название поля для поиска объекта.
        :param value: Значение поля для поиска объекта.
        :param data: Данные для обновления объекта.
        :param ignore_none: Игнорировать пустые значения (True) или нет (False).
        :return: Обновленный объект.
        """
        existing_object = await self.get(
            key=key, value=value, is_return_list=False
        )  # Получаем существующий объект
        if not existing_object:
            raise NotFoundError(message="Object not found")

        return await self.helper._prepare_and_save_object(
            session, data, existing_object, ignore_none=ignore_none
        )

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
        Получить все версии объекта.
        """
        return await self.helper._get_versions_query(session, object_id, order="asc")

    @handle_db_errors
    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_latest_version(
        self, session: AsyncSession, object_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Получить последнюю версию объекта.
        """
        versions = await self.helper._get_versions_query(
            session, object_id, order="desc", limit=1
        )
        return versions[0] if versions else None

    @handle_db_errors
    @session_manager.connection(isolation_level="READ COMMITTED", commit=True)
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

        # Преобразуем версию в словарь данных для обновления
        update_data = {
            attr: getattr(target_version, attr)
            for attr in target_version.__table__.columns.keys()
        }

        return await self.update(
            key="id",
            value=object_id,
            data=update_data,
            ignore_none=False,  # Не игнорируем пустые значения при восстановлении
        )


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
