from contextlib import asynccontextmanager
from functools import wraps
from typing import AsyncGenerator, Callable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.db.database import db_initializer
from app.utils.errors import DatabaseError, NotFoundError
from app.utils.logging_service import db_logger


__all__ = ("session_manager",)


class DatabaseSessionManager:
    """
    Класс для управления асинхронными сессиями базы данных,
    включая поддержку транзакций и зависимости FastAPI.

    Атрибуты:
        session_maker (async_sessionmaker): Фабрика асинхронных сессий.
    """

    def __init__(self, session_maker: async_sessionmaker[AsyncSession]):
        """
        Инициализирует менеджер сессий.

        Args:
            session_maker (async_sessionmaker): Фабрика сессий, созданная с помощью async_sessionmaker.
        """
        self.session_maker = session_maker
        self.logger = db_logger

    @asynccontextmanager
    async def create_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Создаёт и предоставляет новую сессию базы данных.
        Гарантирует закрытие сессии по завершении работы.

        Yields:
            AsyncSession: Асинхронная сессия базы данных.
        """
        async with self.session_maker() as session:
            try:
                yield session
            except Exception as exc:
                self.logger.error(
                    f"Ошибка при создании сессии базы данных: {str(exc)}",
                    exc_info=True,
                )
                raise DatabaseError(
                    message="Failed to create database session"
                )
            finally:
                await session.close()

    @asynccontextmanager
    async def transaction(
        self, session: AsyncSession
    ) -> AsyncGenerator[None, None]:
        """
        Управление транзакцией: коммит при успехе, откат при ошибке.

        Args:
            session (AsyncSession): Сессия базы данных.

        Yields:
            None
        """
        try:
            yield
            await session.commit()
        except Exception as exc:
            await session.rollback()
            self.logger.error(f"Ошибка транзакции: {str(exc)}", exc_info=True)
            raise DatabaseError(message="Transaction failed")

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Зависимость для FastAPI, возвращающая сессию без управления транзакцией.

        Yields:
            AsyncSession: Асинхронная сессия базы данных.
        """
        async with self.create_session() as session:
            try:
                yield session
            except Exception as exc:
                raise DatabaseError(
                    message=f"Failed to get database session - {str(exc)}"
                )

    async def get_transaction_session(
        self,
    ) -> AsyncGenerator[AsyncSession, None]:
        """
        Зависимость для FastAPI, возвращающая сессию с управлением транзакцией.

        Yields:
            AsyncSession: Асинхронная сессия базы данных.
        """
        async with self.create_session() as session:
            try:
                async with self.transaction(session):
                    yield session
            except Exception as exc:
                raise DatabaseError(
                    message=f"Failed to get transaction session - {str(exc)}"
                )

    def connection(
        self, isolation_level: Optional[str] = None, commit: bool = True
    ) -> Callable:
        """
        Декоратор для управления сессией с возможностью
        настройки уровня изоляции и коммита.

        Args:
            isolation_level (Optional[str]): Уровень изоляции для транзакции (например, "SERIALIZABLE").
            commit (bool): Если True, выполняется коммит после вызова метода.

        Returns:
            Callable: Декорированный метод.
        """

        def decorator(method: Callable) -> Callable:
            @wraps(method)
            async def wrapper(*args, **kwargs):
                async with self.session_maker() as session:
                    try:
                        if isolation_level:
                            await session.execute(
                                text(
                                    f"SET TRANSACTION ISOLATION LEVEL {isolation_level}"
                                )
                            )
                        result = await method(*args, session=session, **kwargs)

                        if commit:
                            await session.commit()

                        return result
                    except NotFoundError:
                        raise
                    except Exception as exc:
                        await session.rollback()
                        self.logger.error(
                            f"Ошибка при выполнении транзакции: {str(exc)}",
                            exc_info=True,
                        )
                        raise DatabaseError(
                            message=f"Failed to execute transaction - {str(exc)}"
                        )
                    finally:
                        await session.close()

            return wrapper

        return decorator


# Инициализация менеджера сессий базы данных
session_manager = DatabaseSessionManager(
    session_maker=db_initializer.async_session_maker
)
