from contextlib import asynccontextmanager
from functools import wraps
from typing import AsyncGenerator, Callable, Optional

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.event import listen
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.core.logging_config import db_logger
from backend.core.settings import settings


class DatabaseInitializer:
    """Класс для инициализации движка базы данных и управления сессиями."""

    def __init__(self, url: str, echo: bool, pool_size: int, max_overflow: int):
        """
        Инициализирует движок базы данных и настраивает сессии.

        :param url: URL базы данных.
        :param echo: Логирование SQL-запросов.
        :param pool_size: Размер пула соединений.
        :param max_overflow: Максимальное количество соединений сверх пула.
        """
        self.async_engine: AsyncEngine = create_async_engine(
            url=url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
            future=True,
            pool_pre_ping=True,
        )
        self.async_session_maker = async_sessionmaker(
            bind=self.async_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self.register_logging_events()

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

        listen(
            self.async_engine.sync_engine,
            "before_cursor_execute",
            before_cursor_execute,
        )
        listen(
            self.async_engine.sync_engine, "after_cursor_execute", after_cursor_execute
        )


# Инициализация базы данных с настройками из конфигурации
database = DatabaseInitializer(
    url=settings.database_settings.db_url_asyncpg,
    echo=settings.database_settings.db_echo,
    pool_size=settings.database_settings.db_poolsize,
    max_overflow=settings.database_settings.db_maxoverflow,
)


class DatabaseSessionManager:
    """
    Класс для управления асинхронными сессиями базы данных,
    включая поддержку транзакций и зависимости FastAPI.
    """

    def __init__(self, session_maker: async_sessionmaker[AsyncSession]):
        """
        Инициализирует менеджер сессий.

        :param session_maker: Фабрика сессий, созданная с помощью async_sessionmaker.
        """
        self.session_maker = session_maker

    @asynccontextmanager
    async def create_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Создаёт и предоставляет новую сессию базы данных.
        Гарантирует закрытие сессии по завершении работы.

        :yield: Асинхронная сессия базы данных.
        """
        async with self.session_maker() as session:
            try:
                yield session
            except Exception as e:
                db_logger.error(f"Ошибка при создании сессии базы данных: {e}")
                raise
            finally:
                await session.close()

    @asynccontextmanager
    async def transaction(self, session: AsyncSession) -> AsyncGenerator[None, None]:
        """
        Управление транзакцией: коммит при успехе, откат при ошибке.

        :param session: Сессия базы данных.
        :yield: None
        """
        try:
            yield
            await session.commit()
        except Exception as e:
            await session.rollback()
            db_logger.exception(f"Ошибка транзакции: {e}")
            raise

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Зависимость для FastAPI, возвращающая сессию без управления транзакцией.

        :yield: Асинхронная сессия базы данных.
        """
        async with self.create_session() as session:
            yield session

    async def get_transaction_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Зависимость для FastAPI, возвращающая сессию с управлением транзакцией.

        :yield: Асинхронная сессия базы данных.
        """
        async with self.create_session() as session:
            async with self.transaction(session):
                yield session

    def connection(
        self, isolation_level: Optional[str] = None, commit: bool = True
    ) -> Callable:
        """
        Декоратор для управления сессией с возможностью
        настройки уровня изоляции и коммита.

        :param isolation_level: Уровень изоляции для транзакции (например, "SERIALIZABLE").
        :param commit: Если True, выполняется коммит после вызова метода.
        :return: Декорированный метод.
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
                    except Exception as e:
                        await session.rollback()
                        db_logger.error(f"Ошибка при выполнении транзакции: {e}")
                        raise
                    finally:
                        await session.close()

            return wrapper

        return decorator

    @property
    def session_dependency(self) -> Callable:
        """
        Возвращает зависимость для FastAPI,
        обеспечивающую доступ к сессии без транзакции.

        :return: Зависимость для FastAPI.
        """
        return Depends(self.get_session)

    @property
    def transaction_session_dependency(self) -> Callable:
        """
        Возвращает зависимость для FastAPI с поддержкой транзакций.

        :return: Зависимость для FastAPI.
        """
        return Depends(self.get_transaction_session)


# Инициализация менеджера сессий базы данных
session_manager = DatabaseSessionManager(session_maker=database.async_session_maker)

# Зависимости FastAPI для использования сессий
SessionDep = session_manager.session_dependency
TransactionSessionDep = session_manager.transaction_session_dependency
