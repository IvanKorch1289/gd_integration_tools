import sys
import traceback
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Generic, Type, TypeVar

from fastapi_filter.contrib.sqlalchemy import Filter
from sqlalchemy import Result, asc, delete, desc, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get(
        self,
        session: AsyncSession,
        key: str,
        value: Any,
    ) -> ConcreteTable:
        query = select(self.model).where(getattr(self.model, key) == value)
        result: Result = await session.execute(query)
        return result.scalars().one_or_none()

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def get_by_params(
        self, session: AsyncSession, filter: Filter
    ) -> AsyncGenerator[ConcreteTable, None]:
        query = filter.filter(select(self.model))
        result: Result = await session.execute(query)
        return result.scalars().all()

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def count(self, session: AsyncSession) -> int:
        result: Result = await session.execute(func.count(self.model.id))
        value = result.scalar()
        if not isinstance(value, int):
            raise UnprocessableError(message="Error output type")
        return value

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def first(self, session: AsyncSession, by: str = "id") -> ConcreteTable:
        result: Result = await session.execute(
            select(self.model).order_by(asc(by)).limit(1)
        )
        return result.scalars().one_or_none()

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def last(self, session: AsyncSession, by: str = "id") -> ConcreteTable:
        result: Result = await session.execute(
            select(self.model).order_by(desc(by)).limit(1)
        )
        return result.scalars().one_or_none()

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> ConcreteTable:
        try:
            unsecret_data = await self.model.get_value_from_secret_str(data)
            result: Result = await session.execute(
                insert(self.model).values(**unsecret_data).returning(self.model)
            )
            await session.flush()
            return result.scalars().one_or_none()
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def update(
        self, session: AsyncSession, key: str, value: Any, data: dict[str, Any]
    ) -> ConcreteTable:
        try:
            unsecret_data = await self.model.get_value_from_secret_str(data)
            result: Result = await session.execute(
                update(self.model)
                .where(getattr(self.model, key) == value)
                .values(**unsecret_data)
                .returning(self.model)
            )
            await session.flush()
            return result.scalars().one_or_none()
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    @session_manager.connection(isolation_level="READ COMMITTED")
    async def all(self, session: AsyncSession) -> AsyncGenerator[ConcreteTable, None]:
        result: Result = await session.execute(select(self.model))
        return result.scalars().all()

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
