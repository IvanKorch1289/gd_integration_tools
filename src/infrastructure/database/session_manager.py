from contextlib import asynccontextmanager
from functools import wraps
from typing import AsyncGenerator, Awaitable, Callable, ParamSpec, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.errors import DatabaseError, NotFoundError
from src.infrastructure.database.database import db_initializer, external_db_registry
from src.infrastructure.external_apis.logging_service import db_logger

__all__ = (
    "DatabaseSessionManager",
    "main_session_manager",
    "get_external_session_manager",
)


P = ParamSpec("P")
R = TypeVar("R")


class DatabaseSessionManager:
    """
    Менеджер асинхронных сессий SQLAlchemy.

    Используется на сервисном уровне:
    - create_session() для read-only или ручного управления;
    - transaction() для явного commit/rollback;
    - connection() как декоратор сервисных методов.
    """

    def __init__(
        self, session_maker: async_sessionmaker[AsyncSession], db_name: str = "main"
    ):
        self.session_maker = session_maker
        self.db_name = db_name
        self.logger = db_logger

    @asynccontextmanager
    async def create_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Создаёт и возвращает асинхронную сессию.
        """
        async with self.session_maker() as session:
            try:
                yield session
            except Exception as exc:
                self.logger.error(
                    "Ошибка при работе с сессией БД '%s': %s",
                    self.db_name,
                    str(exc),
                    exc_info=True,
                )
                raise DatabaseError(
                    message=f"Failed to create database session for '{self.db_name}'"
                ) from exc

    @asynccontextmanager
    async def transaction(self, session: AsyncSession) -> AsyncGenerator[None, None]:
        """
        Выполняет commit при успехе и rollback при ошибке.
        """
        try:
            yield
            await session.commit()
        except Exception as exc:
            await session.rollback()
            self.logger.error(
                "Ошибка транзакции в БД '%s': %s", self.db_name, str(exc), exc_info=True
            )
            raise DatabaseError(
                message=f"Transaction failed for '{self.db_name}'"
            ) from exc

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Dependency-совместимый генератор сессии без auto-commit.
        """
        async with self.create_session() as session:
            yield session

    async def get_transaction_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Dependency-совместимый генератор транзакционной сессии.
        """
        async with self.create_session() as session:
            async with self.transaction(session):
                yield session

    def connection(
        self, isolation_level: str | None = None, commit: bool = True
    ) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
        """
        Декоратор сервисного метода.

        Поведение сохраняется прежним:
        - в метод пробрасывается `session=...`;
        - при ошибке выполняется rollback;
        - при `commit=True` выполняется commit.

        Параметр `isolation_level` сохранён для обратной совместимости.
        """

        def decorator(method: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
            @wraps(method)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                async with self.session_maker() as session:
                    try:
                        if isolation_level:
                            await session.connection(
                                execution_options={"isolation_level": isolation_level}
                            )

                        result = await method(*args, session=session, **kwargs)

                        if commit and session.in_transaction():
                            await session.commit()

                        return result

                    except NotFoundError:
                        raise
                    except Exception as exc:
                        if session.in_transaction():
                            await session.rollback()

                        self.logger.error(
                            "Ошибка при выполнении транзакции в БД '%s': %s",
                            self.db_name,
                            str(exc),
                            exc_info=True,
                        )
                        raise DatabaseError(
                            message=(
                                f"Ошибка при выполнении транзакции "
                                f"в БД '{self.db_name}' - {str(exc)}"
                            )
                        ) from exc

            return wrapper

        return decorator


main_session_manager = DatabaseSessionManager(
    session_maker=db_initializer.async_session_maker, db_name="main"
)


def get_external_session_manager(profile_name: str) -> DatabaseSessionManager:
    """
    Возвращает session manager для внешней БД по profile_name.
    """
    initializer = external_db_registry.get_initializer(profile_name)

    return DatabaseSessionManager(
        session_maker=initializer.async_session_maker, db_name=profile_name
    )
