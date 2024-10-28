from contextvars import ContextVar
from functools import wraps
from typing import Any, AsyncGenerator, Generic, Type, TypeVar

from loguru import logger
from sqlalchemy import Result, asc, delete, desc, func, select
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.ext.asyncio import (create_async_engine, async_sessionmaker,
                                    AsyncEngine, AsyncSession)
from sqlalchemy.orm import declarative_base

from src.config.settings import database_settings as ds
from src.infrastructure.errors import DatabaseError
from src.infrastructure.errors.base import NotFoundError, UnprocessableError


class DatabaseInitializer:
    def __init__(self, url: str, echo: bool, pool_size: int, max_overflow: int):
        self.async_engine: AsyncEngine = create_async_engine(
            url=url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
            future=True,
            pool_pre_ping=True
        )

    def get_session(self) -> AsyncSession:
        """Функция-генератор асинхронных сессий к БД."""
        Session: async_sessionmaker = async_sessionmaker(
            bind=self.async_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False
        )
        return Session()


db_init = DatabaseInitializer(
    url=ds.db_url_asyncpg,
    echo=ds.DB_ECHO,
    pool_size=ds.DB_POOLSIZE,
    max_overflow=ds.DB_MAXOVERFLOW
)


CTX_SESSION: ContextVar[AsyncSession] = ContextVar(
    "session", default=db_init.get_session()
)


class Session:
    _ERRORS = (IntegrityError, PendingRollbackError)

    def __init__(self) -> None:
        self._session: AsyncSession = CTX_SESSION.get()

    async def execute(self, query) -> Result:
        try:
            result = await self._session.execute(query)
            return result
        except self._ERRORS:
            raise DatabaseError


def transaction(coro):
    @wraps(coro)
    async def inner(*args, **kwargs):
        session: AsyncSession = db_init.get_session()
        CTX_SESSION.set(session)

        try:
            result = await coro(*args, **kwargs)
            await session.commit()
            return result
        except DatabaseError as error:
            logger.error(f"Rolling back changes.\n{error}")
            await session.rollback()
            raise DatabaseError
        except (IntegrityError, PendingRollbackError) as error:
            logger.error(f"Rolling back changes.\n{error}")
            await session.rollback()
        finally:
            await session.close()

    return inner


meta = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_`%(constraint_name)s`",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

Base = declarative_base(metadata=meta)

ConcreteTable = TypeVar("ConcreteTable", bound=Base)  # type: ignore


class BaseRepository(Generic[ConcreteTable], Session):

    schema_class: Type[ConcreteTable]

    async def _add(self, key: str, value: Any, payload: dict[str, Any]) -> ConcreteTable:
        try:
            schema = self.schema_class(**payload)
            self._session.add(schema)
            await self._session.flush()
            await self._session.refresh(schema)
            return schema
        except self._ERRORS:
            raise DatabaseError

    async def _get(self, key: str, value: Any) -> ConcreteTable:
        query = select(self.schema_class).where(
            getattr(self.schema_class, key) == value
        )
        result: Result = await self.execute(query)

        if not (_result := result.scalars().one_or_none()):
            raise NotFoundError

        return _result

    async def count(self) -> int:
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

    async def _all(self) -> AsyncGenerator[ConcreteTable, None]:
        result: Result = await self.execute(select(self.schema_class))
        schemas = result.scalars().all()

        for schema in schemas:
            yield schema

    async def _delete(self, id_: int) -> None:
        await self.execute(
            delete(self.schema_class).where(self.schema_class.id == id_)
        )
        await self._session.flush()
