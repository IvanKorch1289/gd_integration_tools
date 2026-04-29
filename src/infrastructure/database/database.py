import ssl
from dataclasses import dataclass
from typing import Any, TypeAlias

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from src.core.config.database import DatabaseConnectionSettings
from src.core.config.external_databases import ExternalDatabaseConnectionSettings
from src.core.config.settings import settings
from src.core.enums.database import DatabaseTypeChoices
from src.core.errors import DatabaseError
from src.infrastructure.database.listeners import DatabaseListener
from src.infrastructure.external_apis.logging_service import db_logger

__all__ = (
    "DatabaseBundle",
    "DatabaseInitializer",
    "ExternalDatabaseRegistry",
    "db_initializer",
    "external_db_registry",
)


DatabaseSettings: TypeAlias = (
    DatabaseConnectionSettings | ExternalDatabaseConnectionSettings
)


@dataclass(slots=True)
class DatabaseBundle:
    """
    Контейнер инфраструктурных объектов одной БД.

    Attributes:
        name (str): Логическое имя БД или profile_name.
        settings (DatabaseSettings): Настройки подключения.
        async_engine (AsyncEngine): Асинхронный engine.
        async_session_maker (async_sessionmaker[AsyncSession]):
            Фабрика асинхронных сессий.
        sync_engine (Engine): Синхронный engine.
        sync_session_maker (sessionmaker): Фабрика синхронных сессий.
    """

    name: str
    settings: DatabaseSettings
    async_engine: AsyncEngine
    async_session_maker: async_sessionmaker[AsyncSession]
    sync_engine: Engine
    sync_session_maker: sessionmaker


class DatabaseInitializer:
    """
    Универсальный инициализатор подключения к БД.

    Используется:
    - для основной БД приложения;
    - для внешних БД по profile_name.
    """

    def __init__(self, settings: DatabaseSettings, name: str):
        self.settings = settings
        self.name = name
        self.logger = db_logger

        self.async_engine = self._create_async_engine()
        self.async_session_maker = async_sessionmaker(
            bind=self.async_engine, autoflush=False, expire_on_commit=False
        )

        self.sync_engine = self._create_sync_engine()
        self.sync_session_maker = sessionmaker(
            bind=self.sync_engine, autoflush=False, expire_on_commit=False
        )

        self.db_listener = DatabaseListener(
            async_engine=self.async_engine,
            db_name=self.name,
            slow_query_threshold=self.settings.slow_query_threshold,
        )

    def as_bundle(self) -> DatabaseBundle:
        """
        Возвращает единый контейнер инфраструктурных объектов.
        """
        return DatabaseBundle(
            name=self.name,
            settings=self.settings,
            async_engine=self.async_engine,
            async_session_maker=self.async_session_maker,
            sync_engine=self.sync_engine,
            sync_session_maker=self.sync_session_maker,
        )

    def _engine_kwargs(self) -> dict[str, Any]:
        """Базовые kwargs для create_engine / create_async_engine.

        Для SQLite отключается pool — у него нет параметров pool_size/recycle,
        и SQLAlchemy ругается на их передачу с дефолтным NullPool.
        """
        kwargs: dict[str, Any] = {
            "echo": self.settings.echo,
            "connect_args": self._get_connect_args(),
        }
        if self.settings.type != DatabaseTypeChoices.sqlite:
            kwargs.update(
                {
                    "pool_size": self.settings.pool_size,
                    "max_overflow": self.settings.max_overflow,
                    "pool_recycle": self.settings.pool_recycle,
                    "pool_timeout": self.settings.pool_timeout,
                    "pool_pre_ping": True,
                }
            )
        return kwargs

    def _create_async_engine(self) -> AsyncEngine:
        """
        Создаёт и настраивает асинхронный engine SQLAlchemy.
        """
        return create_async_engine(
            url=self.settings.async_connection_url, **self._engine_kwargs()
        )

    def _create_sync_engine(self) -> Engine:
        """
        Создаёт и настраивает синхронный engine SQLAlchemy.
        """
        return create_engine(
            url=self.settings.sync_connection_url, **self._engine_kwargs()
        )

    def _get_connect_args(self) -> dict[str, Any]:
        """
        Генерирует driver-level параметры подключения.
        """
        connect_args: dict[str, Any] = {}

        if self.settings.type == DatabaseTypeChoices.postgresql:
            connect_args.update(
                {
                    "command_timeout": self.settings.command_timeout,
                    "timeout": self.settings.connect_timeout,
                }
            )

            if self.settings.ca_bundle:
                ssl_context = ssl.create_default_context(cafile=self.settings.ca_bundle)
                connect_args["ssl"] = ssl_context

        elif self.settings.type == DatabaseTypeChoices.oracle:
            connect_args.update({"tcp_connect_timeout": self.settings.connect_timeout})

        return connect_args

    async def initialize_async_pool(self) -> None:
        """
        Предварительно прогревает асинхронный пул соединений.
        """
        connections = []

        try:
            pool_size = getattr(self.settings, "pool_size", 1)

            for _ in range(pool_size):
                conn = await self.async_engine.connect()
                connections.append(conn)

            self.logger.info(
                "Асинхронный пул соединений инициализирован",
                extra={"db_name": self.name},
            )
        except (OSError, TimeoutError):
            self.logger.error(
                "Ошибка инициализации асинхронного пула соединений",
                extra={"db_name": self.name},
                exc_info=True,
            )
        finally:
            for conn in connections:
                await conn.close()

    def get_async_engine(self) -> AsyncEngine:
        """
        Возвращает асинхронный engine.
        """
        return self.async_engine

    def get_sync_engine(self) -> Engine:
        """
        Возвращает синхронный engine.
        """
        return self.sync_engine

    async def dispose_sync(self) -> None:
        """
        Закрывает синхронные соединения.
        """
        try:
            self.sync_engine.dispose()
            self.logger.info(
                "Синхронные соединения закрыты", extra={"db_name": self.name}
            )
        except (RuntimeError, OSError):
            self.logger.error(
                "Ошибка закрытия синхронных соединений",
                extra={"db_name": self.name},
                exc_info=True,
            )

    async def dispose_async(self) -> None:
        """
        Закрывает асинхронные соединения.
        """
        try:
            await self.async_engine.dispose()
            self.logger.info(
                "Асинхронные соединения закрыты", extra={"db_name": self.name}
            )
        except (RuntimeError, OSError):
            self.logger.error(
                "Ошибка закрытия асинхронных соединений",
                extra={"db_name": self.name},
                exc_info=True,
            )

    async def close(self) -> None:
        """
        Закрывает все соединения с БД.
        """
        await self.dispose_sync()
        await self.dispose_async()

    async def check_connection(self) -> bool:
        """
        Проверяет работоспособность подключения.

        Returns:
            bool: True, если соединение работает корректно.

        Raises:
            DatabaseError: При ошибке проверки подключения.
        """
        ping_sql = (
            "SELECT 1 FROM dual"
            if self.settings.type == DatabaseTypeChoices.oracle
            else "SELECT 1"
        )

        async with self.async_session_maker() as session:
            try:
                result = await session.execute(text(ping_sql))

                if result.scalar_one_or_none() != 1:
                    raise DatabaseError(
                        message=f"Ошибка проверки подключения к БД '{self.name}'"
                    )

                return True
            except Exception as exc:
                raise DatabaseError(
                    message=f"Ошибка проверки соединения '{self.name}': {exc}"
                ) from exc


class ExternalDatabaseRegistry:
    """
    Реестр внешних БД.

    Поднимает и хранит инициализаторы внешних подключений
    по `profile_name`.
    """

    def __init__(self, configs: dict[str, ExternalDatabaseConnectionSettings]):
        self.logger = db_logger
        self._initializers: dict[str, DatabaseInitializer] = {}

        for profile_name, config in configs.items():
            self._initializers[profile_name] = DatabaseInitializer(
                settings=config, name=profile_name
            )

    def get_initializer(self, profile_name: str) -> DatabaseInitializer:
        """
        Возвращает инициализатор внешней БД по profile_name.
        """
        initializer = self._initializers.get(profile_name)

        if initializer is None:
            raise DatabaseError(
                message=f"Внешняя БД '{profile_name}' не зарегистрирована"
            )

        return initializer

    def get_bundle(self, profile_name: str) -> DatabaseBundle:
        """
        Возвращает bundle внешней БД по profile_name.
        """
        return self.get_initializer(profile_name).as_bundle()

    def list_profiles(self) -> list[str]:
        """
        Возвращает список зарегистрированных профилей.
        """
        return list(self._initializers.keys())

    async def check_connection(self, profile_name: str) -> bool:
        """
        Проверяет доступность конкретной внешней БД.
        """
        return await self.get_initializer(profile_name).check_connection()

    async def initialize_all_pools(self) -> None:
        """
        Прогревает пулы всех активных внешних БД.
        """
        for initializer in self._initializers.values():
            await initializer.initialize_async_pool()

    async def close_all(self) -> None:
        """
        Закрывает соединения всех внешних БД.
        """
        for initializer in self._initializers.values():
            await initializer.close()


db_initializer = DatabaseInitializer(settings=settings.database, name="main")

external_db_registry = ExternalDatabaseRegistry(
    configs=settings.external_databases.profiles
)
