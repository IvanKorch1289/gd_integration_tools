from typing import Any, Dict

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from app.config.settings import DatabaseConnectionSettings, settings
from app.infra.db.listeners import DatabaseListener
from app.utils.errors import DatabaseError
from app.utils.logging_service import db_logger


__all__ = ("db_initializer",)


class DatabaseInitializer:
    """Класс для инициализации и управления подключениями к базе данных.

    Обеспечивает создание синхронных и асинхронных движков БД, управление пулом соединений,
    логирование SQL-запросов и проверку работоспособности подключения.

    Args:
        settings (DatabaseConnectionSettings): Настройки подключения к БД

    Attributes:
        async_engine (AsyncEngine): Асинхронный движок SQLAlchemy
        async_session_maker (async_sessionmaker): Фабрика асинхронных сессий
        sync_engine (Engine): Синхронный движок SQLAlchemy
        sync_session_maker (sessionmaker): Фабрика синхронных сессий
    """

    def __init__(self, settings: DatabaseConnectionSettings):
        self.settings: DatabaseConnectionSettings = settings
        self.logger = db_logger

        # Основной асинхронный движок
        self.async_engine = self._create_async_engine()
        self.async_session_maker = async_sessionmaker(
            bind=self.async_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        # Синхронный движок для миграций
        self.sync_engine = self._create_sync_engine()
        self.sync_session_maker = sessionmaker(
            bind=self.sync_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        self.db_listener = DatabaseListener(
            async_engine=self.async_engine,
        )

    def _create_async_engine(self) -> AsyncEngine:
        """Создает и настраивает асинхронный движок базы данных.

        Returns:
            AsyncEngine: Настроенный асинхронный движок SQLAlchemy
        """
        return create_async_engine(
            url=self.settings.async_connection_url,
            echo=self.settings.echo,
            pool_size=self.settings.pool_size,
            max_overflow=self.settings.max_overflow,
            pool_recycle=self.settings.pool_recycle,
            pool_timeout=self.settings.pool_timeout,
            connect_args=self._get_connect_args(),
        )

    def _create_sync_engine(self):
        """Создает и настраивает синхронный движок базы данных.

        Returns:
            Engine: Настроенный синхронный движок SQLAlchemy
        """
        return create_engine(
            url=self.settings.sync_connection_url,
            echo=self.settings.echo,
            pool_size=self.settings.pool_size,
            max_overflow=self.settings.max_overflow,
            pool_recycle=self.settings.pool_recycle,
            pool_timeout=self.settings.pool_timeout,
        )

    def _get_connect_args(self) -> Dict[str, Any]:
        """Генерирует дополнительные аргументы для подключения к БД.

        Returns:
            dict: Дополнительные параметры подключения
        """
        connect_args: dict = {}

        if self.settings.type == "postgresql":
            connect_args.update(
                {
                    "command_timeout": self.settings.command_timeout,
                    "timeout": self.settings.connect_timeout,
                }
            )

            if self.settings.ca_bundle:
                import ssl

                ssl_context = ssl.create_default_context(
                    cafile=self.settings.ca_bundle
                )
                connect_args["ssl"] = ssl_context

        elif self.settings.type == "oracle":
            connect_args.update(
                {
                    "encoding": "UTF-8",
                    "nencoding": "UTF-8",
                }
            )

        return connect_args

    async def initialize_async_pool(self):
        """Предварительная инициализация соединений в асинхронном пуле."""
        connections = []
        try:
            for _ in range(self.async_engine.pool.size()):  # type: ignore
                conn = await self.async_engine.connect()
                connections.append(conn)
            self.logger.info("Асинхронный пул соединений инициализирован")
        except Exception:
            self.logger.error(
                "Ошибка инициализации асинхронного пула соединений",
                exc_info=True,
            )
        finally:
            for conn in connections:
                await conn.close()

    def get_async_engine(self):
        """Возвращает асинхронный движок базы данных.

        Returns:
            AsyncEngine: Асинхронный движок SQLAlchemy
        """
        return self.async_engine

    def get_sync_engine(self):
        """Возвращает синхронный движок для миграций Alembic.

        Returns:
            Engine: Синхронный движок SQLAlchemy
        """
        return self.sync_engine

    async def dispose_sync(self):
        """Закрывает все синхронные соединения."""
        try:
            self.sync_engine.dispose()
            self.logger.info("Синхронные соединения закрыты")
        except Exception:
            self.logger.error(
                "Ошибка закрытия синхронных соединений", exc_info=True
            )

    async def dispose_async(self):
        """Закрывает все асинхронные соединения."""
        try:
            await self.async_engine.dispose()
            self.logger.info("Асинхронные соединения закрыты")
        except Exception:
            self.logger.error(
                "Ошибка закрытия асинхронных соединений", exc_info=True
            )

    async def close(self):
        """Закрывает все соединения с базой данных."""
        await self.dispose_sync()
        await self.dispose_async()

    async def check_connection(self) -> bool:
        """Проверяет работоспособность подключения к базе данных.

        Returns:
            bool: True если подключение активно и работает корректно

        Raises:
            DatabaseError: При ошибке подключения или неверном результате
        """
        async with self.async_session_maker() as session:
            try:
                result = await session.execute(text("SELECT 1"))
                if result.scalar_one_or_none() != 1:
                    raise DatabaseError(
                        message="Ошибка проверки подключения к БД"
                    )
                return True
            except Exception as exc:
                raise DatabaseError(
                    message=f"Ошибка проверки соединения: {str(exc)}",
                ) from exc


# Инициализатор БД с конфигурацией из настроек
db_initializer = DatabaseInitializer(settings=settings.database)
