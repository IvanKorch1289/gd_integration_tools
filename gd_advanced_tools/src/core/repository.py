from typing import Any, AsyncGenerator, Generic, Type, TypeVar

from fastapi.encoders import jsonable_encoder
from sqlalchemy import Result, asc, delete, desc, func, select, update

from gd_advanced_tools.src.core.database import Base
from gd_advanced_tools.src.core.errors import DatabaseError, NotFoundError, UnprocessableError
from gd_advanced_tools.src.core.session import Session


ConcreteTable = TypeVar("ConcreteTable", bound=Base)


class BaseRepository(Generic[ConcreteTable], Session):
    """Базовый класс взаимодействия с БД."""

    schema_class: Type[ConcreteTable]

    async def _get(self, key: str, value: Any) -> ConcreteTable:
        query = select(self.schema_class).where(
            getattr(self.schema_class, key) == value
        )
        result: Result = await self.execute(query)
        if not (_result := result.scalars().one_or_none()):
            raise NotFoundError
        return _result

    async def _count(self) -> int:
        result: Result = await self.execute(func.count(self.schema_class.id))
        value = result.scalar()
        if not isinstance(value, int):
            raise UnprocessableError(
                message=(
                    "For some reason count function returned not an integer."
                    f"Value: {value}"
                ),
            )
        return value

    async def _first(self, by: str = "id") -> ConcreteTable:
        result: Result = await self.execute(
            select(self.schema_class).order_by(asc(by)).limit(1)
        )

        if not (_result := result.scalar_one_or_none()):
            raise NotFoundError

        return _result

    async def _last(self, by: str = "id") -> ConcreteTable:
        result: Result = await self.execute(
            select(self.schema_class).order_by(desc(by)).limit(1)
        )

        if not (_result := result.scalar_one_or_none()):
            raise NotFoundError

        return _result

    async def _save(self, payload: dict[str, Any]) -> ConcreteTable:
        try:
            schema = self.schema_class(**payload)
            self._session.add(schema)
            await self._session.flush()
            await self._session.refresh(schema)
            return schema
        except self._ERRORS:
            raise DatabaseError

    async def _update(self, key: str, value: Any, payload: dict[str, Any]) -> ConcreteTable:
        await self.execute(
            update(self.schema_class).where(getattr(self.schema_class, key) == value).values(payload)
        )
        await self._session.flush()
        await self._session.commit()
        return await self._get(key=key, value=value)

    async def _all(self) -> AsyncGenerator[ConcreteTable, None]:
        result: Result = await self.execute(select(self.schema_class))
        schemas = result.scalars().all()

        for schema in schemas:
            yield schema

    async def _delete(self, id: int) -> None:
        await self.execute(
            delete(self.schema_class).where(self.schema_class.id == id)
        )
        await self._session.flush()
