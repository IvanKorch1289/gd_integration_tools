from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Generic, Type, TypeVar

from sqlalchemy import Result, asc, delete, desc, func, insert, select, update

from gd_advanced_tools.models.base import Base
from gd_advanced_tools.core.errors import DatabaseError, NotFoundError, UnprocessableError
from gd_advanced_tools.core.session import Session


ConcreteTable = TypeVar("ConcreteTable", bound=Base)


class AbstractRepository(ABC):

    @abstractmethod
    async def get():
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


class SQLAlchemyRepository(AbstractRepository, Generic[ConcreteTable], Session):
    """Базовый класс взаимодействия с БД."""

    model: Type[ConcreteTable] = None

    async def get(self, key: str, value: Any) -> ConcreteTable:
        query = select(self.model).where(getattr(self.model, key) == value)
        result: Result = await self.execute(query)
        if not (_result := result.scalars().one_or_none()):
            raise NotFoundError(message=f'Not Found ({key}={value})')
        return _result

    async def count(self) -> int:
        result: Result = await self.execute(func.count(self.model.id))
        value = result.scalar()
        if not isinstance(value, int):
            raise UnprocessableError(message='Error output type')
        return value

    async def first(self, by: str = "id") -> ConcreteTable:
        result: Result = await self.execute(
            select(self.model).order_by(asc(by)).limit(1)
        )

        if not (_result := result.scalars().one_or_none()):
            raise NotFoundError(message='Table is empty')
        return _result

    async def last(self, by: str = "id") -> ConcreteTable:
        result: Result = await self.execute(
            select(self.model).order_by(desc(by)).limit(1)
        )

        if not (_result := result.scalars().one_or_none()):
            raise NotFoundError(message='Table is empty')
        return _result

    async def add(self, data: dict[str, Any]) -> ConcreteTable:
        try:
            result: Result = await self.execute(insert(self.model).values(**data).returning(self.model))
            await self._session.flush()
            await self._session.commit()
            return result.scalars().one_or_none()
        except self._ERRORS as ex:
            raise DatabaseError

    async def update(self, key: str, value: Any, data: dict[str, Any]) -> ConcreteTable:
        try:
            result: Result = await self.execute(update(self.model).where(getattr(self.model, key) == value).values(**data).returning(self.model))
            await self._session.flush()
            await self._session.commit()
            return result.scalars().one_or_none()
        except self._ERRORS:
            raise DatabaseError

    async def all(self) -> AsyncGenerator[ConcreteTable, None]:
        result: Result = await self.execute(select(self.model))
        instances = result.scalars().all()

        for instance in instances:
            yield instance

    async def delete(self, key: int, value: Any) -> None:
        try:
            result = await self.execute(delete(self.model).where(getattr(self.model, key) == value).returning(self.model.id))
            await self._session.flush()
            await self._session.commit()
            return result.scalar_one()
        except self._ERRORS:
            raise DatabaseError
