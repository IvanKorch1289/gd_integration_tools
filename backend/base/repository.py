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
from sqlalchemy.orm import selectinload
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

    async def _refresh_with_relationships(
        self, session: AsyncSession, obj: ConcreteTable
    ) -> None:
        """
        Обновляет объект и загружает все его связи.
        """
        mapper = inspect(obj.__class__)
        relationships = [rel.key for rel in mapper.relationships]
        await session.refresh(obj, attribute_names=relationships)

    async def _get_loaded_object(
        self,
        session: AsyncSession,
        query_or_object: Union[Select, ConcreteTable],
        is_return_list: bool = False,
    ) -> Optional[ConcreteTable] | List[ConcreteTable]:
        """
        Выполняет запрос или подгружает связи для объекта.
        """
        try:
            mapper = inspect(self.model)
            relationships = [rel.key for rel in mapper.relationships]

            if isinstance(query_or_object, Select):
                if self.load_joined_models:
                    options = [
                        selectinload(getattr(self.model, key)) for key in relationships
                    ]
                    query_or_object = query_or_object.options(*options)

                result: Result = await session.execute(query_or_object)
                return (
                    result.scalars().all()
                    if is_return_list
                    else result.scalar_one_or_none()
                )

            elif self.load_joined_models:
                if query_or_object not in session:
                    session.add(query_or_object)
                    await session.flush()

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
                return result.scalar_one_or_none()

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
        """
        try:
            result: Result = await session.execute(func.count(self.model.id))
            return result.scalar()
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def first_or_last(
        self, session: AsyncSession, by: str = "id", order: str = "asc"
    ) -> Optional[ConcreteTable]:
        """
        Получить первый или последний объект в таблице, отсортированный по указанному полю.
        """
        try:
            order_by = asc(by) if order == "asc" else desc(by)
            query = select(self.model).order_by(order_by).limit(1)
            return await self._get_loaded_object(session, query)
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="READ COMMITTED", commit=True)
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> ConcreteTable:
        """
        Добавить новый объект в таблицу.
        """
        try:
            unsecret_data = await self.model.get_value_from_secret_str(data)
            new_object = self.model(**unsecret_data)
            session.add(new_object)
            await session.flush()
            await self._refresh_with_relationships(session, new_object)
            return new_object
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def update(
        self, session: AsyncSession, key: str, value: Any, data: dict[str, Any]
    ) -> ConcreteTable:
        """
        Обновить объект в таблице.
        """
        try:
            unsecret_data = await self.model.get_value_from_secret_str(data)
            existing_object = await self.get(session, key, value)
            if not existing_object:
                raise NotFoundError(message="Object not found")

            for field, new_value in unsecret_data.items():
                setattr(existing_object, field, new_value)

            session.add(existing_object)
            await session.flush()
            await self._refresh_with_relationships(session, existing_object)
            return existing_object
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def all(self, session: AsyncSession) -> List[ConcreteTable]:
        """
        Получить все объекты из таблицы.
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
    ) -> List[Dict[str, Any]]:
        """
        Получить все версии объекта по его id, включая id транзакции.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :return: Список всех версий объекта с информацией о транзакции.
        """
        try:
            VersionModel = version_class(self.model)
            result = await session.execute(
                select(VersionModel)
                .filter(VersionModel.id == object_id)
                .order_by(VersionModel.transaction_id)
            )
            versions = result.scalars().all()

            return [
                {
                    "transaction_id": version.transaction_id,
                    "data": version,
                }
                for version in versions
            ]
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_latest_version(
        self, session: AsyncSession, object_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Получить последнюю версию объекта, включая id транзакции.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :return: Последняя версия объекта с информацией о транзакции, если найдена, иначе None.
        """
        try:
            VersionModel = version_class(self.model)
            result = await session.execute(
                select(VersionModel)
                .filter(VersionModel.id == object_id)
                .order_by(VersionModel.transaction_id.desc())
                .limit(1)
            )
            version = result.scalars().first()

            if not version:
                return None

            return {
                "transaction_id": version.transaction_id,
                "data": version,
            }
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def restore_to_version(
        self, session: AsyncSession, object_id: int, transaction_id: int
    ) -> Dict[str, Any]:
        """
        Восстановить объект до указанной версии и вернуть информацию о транзакции.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :param transaction_id: ID транзакции, до которой нужно восстановить объект.
        :return: Восстановленный объект с информацией о транзакции.
        :raises NotFoundError: Если версия или объект не найдены.
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

            return {
                "transaction_id": transaction_id,
                "data": parent_obj,
            }
        except Exception as exc:
            raise DatabaseError(message=str(exc))

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_changes(
        self, session: AsyncSession, object_id: int
    ) -> List[Dict[str, Any]]:
        """
        Получить список изменений атрибутов объекта с указанием id транзакции.

        :param session: Асинхронная сессия SQLAlchemy.
        :param object_id: ID объекта.
        :return: Список изменений атрибутов объекта с информацией о транзакции.
        """
        try:
            versions = await self.get_all_versions(object_id=object_id)
            if not versions:
                return None

            changes = []
            for i in range(1, len(versions)):
                prev_version = versions[i - 1]["data"]
                current_version = versions[i]["data"]
                transaction_id = versions[i]["transaction_id"]

                diff = {
                    attr: {
                        "old": getattr(prev_version, attr),
                        "new": getattr(current_version, attr),
                    }
                    for attr in current_version.__table__.columns.keys()
                    if getattr(current_version, attr) != getattr(prev_version, attr)
                }

                if diff:
                    changes.append(
                        {
                            "transaction_id": transaction_id,
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
    """
    repository_name = f"{model.__name__}Repository"

    try:
        repository_module = importlib.import_module(
            f"backend.{model.__tablename__}.repository"
        )
        repository_class = getattr(repository_module, repository_name)
        return repository_class
    except (ImportError, AttributeError) as exc:
        raise ValueError(
            f"Репозиторий для модели {model.__name__} не найден: {str(exc)}"
        )
