from sqlalchemy import create_engine, text
from sqlalchemy.event import listen
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session

from app.config.settings import DatabaseSettings, settings
from app.utils.errors import DatabaseError
from app.utils.logging import db_logger


__all__ = ("db_initializer",)


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

    async def check_connection(self) -> bool:
        """Проверяет подключение к базе данных.

        Returns:
            bool: True, если подключение успешно.

        Raises:
            DatabaseError: Если подключение к базе данных не удалось.
        """

        async with self.async_session_maker() as session:
            try:
                result = await session.execute(text("SELECT 1"))
                if result.scalar_one_or_none() != 1:
                    raise DatabaseError(message="Database not connected")
                return True
            except Exception as exc:
                raise DatabaseError(
                    message=f"Database not connected: {str(exc)}",
                )


# Инициализация базы данных с настройками из конфигурации
db_initializer = DatabaseInitializer(settings=settings.database)
