from contextlib import asynccontextmanager
from functools import wraps
from typing import AsyncGenerator, Callable, Optional

from fastapi import Depends
from sqlalchemy import create_engine, text
from sqlalchemy.event import listen
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session

from app.core.errors import DatabaseError, NotFoundError
from app.core.logging import db_logger
from app.core.settings import DatabaseSettings, settings


__all__ = (
    "db_initializer",
    "session_manager",
)


class DatabaseInitializer:
    """
    Класс для инициализации движков PostgreSQL/Oracle.
    """

    def __init__(self, settings: DatabaseSettings):
        self.settings: DatabaseSettings = settings

        # Асинхронный движок
        self.async_engine = self._create_async_engine()
        self.async_session_maker = async_sessionmaker(
            bind=self.async_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        # Синхронный движок
        self.sync_engine = self._create_sync_engine()
        self.sync_session_maker = sessionmaker(
            bind=self.sync_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        self.register_logging_events()

    def _create_async_engine(self) -> AsyncEngine:
        """Создает асинхронный движок."""
        return create_async_engine(
            url=self.settings.db_url_async,
            echo=self.settings.db_echo,
            pool_size=self.settings.db_pool_size,
            max_overflow=self.settings.db_max_overflow,
            pool_recycle=self.settings.db_pool_recycle,
            pool_timeout=self.settings.db_pool_timeout,
            connect_args=self._get_connect_args(),
        )

    def _create_sync_engine(self):
        """Создает синхронный движок."""
        return create_engine(
            url=self.settings.db_url_sync,
            echo=self.settings.db_echo,
            pool_size=self.settings.db_pool_size,
            max_overflow=self.settings.db_max_overflow,
            pool_recycle=self.settings.db_pool_recycle,
            pool_timeout=self.settings.db_pool_timeout,
            connect_args=self._get_connect_args(),
        )

    def _get_connect_args(self) -> dict:
        """Возвращает дополнительные аргументы подключения."""
        connect_args = {}

        # Общие параметры для всех СУБД
        if self.settings.db_type == "postgresql":
            # Таймауты
            connect_args.update(
                {
                    "command_timeout": self.settings.db_command_timeout,
                    "timeout": self.settings.db_connect_timeout,
                }
            )

            # SSL
            if self.settings.db_ssl_ca:
                import ssl

                ssl_context = ssl.create_default_context(
                    cafile=self.settings.db_ssl_ca  # Путь к CA-сертификату
                )
                connect_args["ssl"] = ssl_context

        elif self.settings.db_type == "oracle":
            connect_args.update(
                {
                    "encoding": "UTF-8",
                    "nencoding": "UTF-8",
                }
            )

        return connect_args

    def register_logging_events(self):
        """Регистрирует события для логирования SQL-запросов."""

        def before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            db_logger.info("SQL Statement: %s", statement)
            db_logger.info("Parameters: %s", parameters)

        def after_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            db_logger.info("SQL Execution Completed.")

        # Логирование для асинхронного движка
        listen(
            self.async_engine.sync_engine,
            "before_cursor_execute",
            before_cursor_execute,
        )
        listen(
            self.async_engine.sync_engine, "after_cursor_execute", after_cursor_execute
        )

        # Логирование для синхронного движка
        listen(
            self.sync_engine,
            "before_cursor_execute",
            before_cursor_execute,
        )
        listen(self.sync_engine, "after_cursor_execute", after_cursor_execute)

    def get_sync_engine(self):
        """
        Возвращает синхронный движок для Alembic.

        Returns:
            Engine: Синхронный движок SQLAlchemy.
        """
        return self.sync_engine

    def get_sync_session(self) -> Session:
        """
        Возвращает синхронную сессию для Alembic.

        Returns:
            Session: Синхронная сессия SQLAlchemy.
        """
        return self.sync_session_maker()


# Инициализация базы данных с настройками из конфигурации
db_initializer = DatabaseInitializer(settings=settings.database)


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
                db_logger.error(f"Ошибка при создании сессии базы данных: {exc}")
                raise DatabaseError(message="Failed to create database session")
            finally:
                await session.close()

    @asynccontextmanager
    async def transaction(self, session: AsyncSession) -> AsyncGenerator[None, None]:
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
            db_logger.exception(f"Ошибка транзакции: {exc}")
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

    async def get_transaction_session(self) -> AsyncGenerator[AsyncSession, None]:
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
                        db_logger.error(f"Ошибка при выполнении транзакции: {str(exc)}")
                        raise DatabaseError(
                            message=f"Failed to execute transaction - {str(exc)}"
                        )
                    finally:
                        await session.close()

            return wrapper

        return decorator

    @property
    def session_dependency(self) -> Callable:
        """
        Возвращает зависимость для FastAPI,
        обеспечивающую доступ к сессии без транзакции.

        Returns:
            Callable: Зависимость для FastAPI.
        """
        return Depends(self.get_session)

    @property
    def transaction_session_dependency(self) -> Callable:
        """
        Возвращает зависимость для FastAPI с поддержкой транзакций.

        Returns:
            Callable: Зависимость для FastAPI.
        """
        return Depends(self.get_transaction_session)


# Инициализация менеджера сессий базы данных
session_manager = DatabaseSessionManager(
    session_maker=db_initializer.async_session_maker
)

# Зависимости FastAPI для использования сессий
SessionDep = session_manager.session_dependency
TransactionSessionDep = session_manager.transaction_session_dependency
