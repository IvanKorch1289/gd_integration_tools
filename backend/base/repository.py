import sys
import traceback
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Coroutine, Generic, List, Type, TypeVar

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

    @abstractmethod
    async def get():
        raise NotImplementedError

    @abstractmethod
    async def get_by_params():
        raise NotImplementedError

    @abstractmethod
    async def count():
        raise NotImplementedError

    @abstractmethod
    async def first():
        raise NotImplementedError

    @abstractmethod
    async def last():
        raise NotImplementedError

    @abstractmethod
    async def add():
        raise NotImplementedError

    @abstractmethod
    async def update():
        raise NotImplementedError

    @abstractmethod
    async def all():
        raise NotImplementedError

    @abstractmethod
    async def delete():
        raise NotImplementedError


class SQLAlchemyRepository(AbstractRepository, Generic[ConcreteTable]):
    """Базовый класс взаимодействия с БД."""

    model: Type[ConcreteTable] = None
    load_joinded_models: bool = False

    async def _get_loaded_object(
        self, session: AsyncSession, query: Select, is_return_list: bool = False
    ) -> ConcreteTable | None:
        result: Result = await session.execute(query)
        if result and self.load_joinded_models:
            mapper = inspect(self.model)
            relationships = [rel.key for rel in mapper.relationships]
            options = [joinedload(getattr(self.model, key)) for key in relationships]

            query_with_options = query.options(*options)
            result = await session.execute(query_with_options)

        return (
            result.unique().scalars()
            if is_return_list
            else result.unique().scalar_one_or_none()
        )

    async def _execute_stmt(self, session: AsyncSession, stmt: Insert | Update):
        await session.flush()

        result = await session.execute(stmt)

        if not result:
            raise ValueError("Failed to create/update record")

        primary_key = result.unique().scalar_one_or_none().id

        query = select(self.model).where(self.model.id == primary_key)
        return await self._get_loaded_object(session, query)

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get(
        self,
        session: AsyncSession,
        key: str,
        value: Any,
    ) -> ConcreteTable:
        query = select(self.model).where(getattr(self.model, key) == value)
        return await self._get_loaded_object(session, query)

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_by_params(
        self, session: AsyncSession, filter: Filter
    ) -> AsyncGenerator[ConcreteTable, None]:
        query = filter.filter(select(self.model))
        return await self._get_loaded_object(session, query, is_return_list=True)

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def count(self, session: AsyncSession) -> int:
        result: Result = await session.execute(func.count(self.model.id))
        value = result.scalar()
        if not isinstance(value, int):
            raise UnprocessableError(message="Error output type")
        return value

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def first(self, session: AsyncSession, by: str = "id") -> ConcreteTable:
        query = select(self.model).order_by(asc(by)).limit(1)
        return await self._get_loaded_object(session, query)

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def last(self, session: AsyncSession, by: str = "id") -> ConcreteTable:
        query = select(self.model).order_by(desc(by)).limit(1)
        return await self._get_loaded_object(session, query)

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> ConcreteTable:
        try:
            unsecret_data = await self.model.get_value_from_secret_str(data)
            stmt = insert(self.model).values(**unsecret_data).returning(self.model)
            return await self._execute_stmt(session, stmt)
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def add_many(
        self, session: AsyncSession, data_list: list[dict[str, Any]]
    ) -> ConcreteTable:
        try:
            results = []

            for data in data_list:
                result = await self.add(data=data)
                results.append(result)

            return results
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def update(
        self, session: AsyncSession, key: str, value: Any, data: dict[str, Any]
    ) -> ConcreteTable:
        try:
            unsecret_data = await self.model.get_value_from_secret_str(data)
            stmt = (
                update(self.model)
                .where(getattr(self.model, key) == value)
                .values(**unsecret_data)
                .returning(self.model)
            )
            return await self._execute_stmt(session, stmt)
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def all(
        self, session: AsyncSession
    ) -> Coroutine[Any, Any, List[ConcreteTable]]:
        query = select(self.model)
        return await self._get_loaded_object(session, query, is_return_list=True)

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def delete(self, session: AsyncSession, key: int, value: Any) -> None:
        try:
            result = await session.execute(
                delete(self.model)
                .where(getattr(self.model, key) == value)
                .returning(self.model.id)
            )
            await session.flush()
            return result.scalars().one()
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex
