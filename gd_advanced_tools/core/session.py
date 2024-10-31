from contextvars import ContextVar

from sqlalchemy import Result
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from gd_advanced_tools.core.database import DB_INIT
from gd_advanced_tools.core.errors import DatabaseError


def get_session() -> AsyncSession:
    """Функция-генератор асинхронных сессий к БД."""
    Session: async_sessionmaker = async_sessionmaker(
        bind=DB_INIT.async_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False
    )
    return Session()


CTX_SESSION: ContextVar[AsyncSession] = ContextVar("session", default=get_session())


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
