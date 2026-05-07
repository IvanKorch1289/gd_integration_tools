import ssl
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, TypeAlias

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.external_databases import (
    ExternalDatabaseConnectionSettings,
)
from src.backend.core.config.settings import settings
from src.backend.core.enums.database import DatabaseTypeChoices
from src.backend.core.errors import DatabaseError
from src.backend.infrastructure.database.listeners import DatabaseListener
from src.backend.infrastructure.external_apis.logging_service import db_logger

__all__ = (
    "DatabaseBundle",
    "DatabaseInitializer",
    "ExternalDatabaseRegistry",
    "db_initializer",
    "external_db_registry",
    "get_db_initializer",
    "get_external_db_registry",
)


DatabaseSettings: TypeAlias = (
    DatabaseConnectionSettings | ExternalDatabaseConnectionSettings
)


@dataclass(slots=True)
class DatabaseBundle:
    """
    Контейнер инфраструктурных объектов одной БД.

    Принцип проекта — async-first: все hot-path SQL-вызовы идут через
    ``async_engine`` / ``async_session_maker``. Sync-варианты (Wave F.3
    F.3) опциональны и поднимаются только если установлен sync-драйвер
    (``psycopg``/``oracledb``/``pysqlite``); используются библиотеками,
    которые ещё не поддерживают async (APScheduler SQLAlchemyJobStore).
    При недоступности sync-драйвера соответствующие потребители
    получают ``None`` и должны иметь fallback (memory jobstore и т.п.).

    Attributes:
        name (str): Логическое имя БД или profile_name.
        settings (DatabaseSettings): Настройки подключения.
        async_engine (AsyncEngine): Асинхронный engine (обязателен).
        async_session_maker (async_sessionmaker[AsyncSession]):
            Фабрика асинхронных сессий (обязательна).
        sync_engine (Engine | None): Синхронный engine; ``None`` если
            sync-драйвер не установлен.
        sync_session_maker (sessionmaker | None): Фабрика синхронных
            сессий; ``None`` если ``sync_engine is None``.
    """

    name: str
    settings: DatabaseSettings
    async_engine: AsyncEngine
    async_session_maker: async_sessionmaker[AsyncSession]
    sync_engine: Engine | None
    sync_session_maker: sessionmaker | None


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

        # Wave F.3: async-first. Sync-engine опционален — если sync-драйвер
        # (psycopg/oracledb/pysqlite) не установлен, не валим старт; вместо
        # этого пишем warning и оставляем None. Потребители (APScheduler
        # SQLAlchemyJobStore) обязаны иметь fallback.
        self.sync_engine: Engine | None
        self.sync_session_maker: sessionmaker | None
        try:
            self.sync_engine = self._create_sync_engine()
            self.sync_session_maker = sessionmaker(
                bind=self.sync_engine, autoflush=False, expire_on_commit=False
            )
        except ModuleNotFoundError as exc:
            self.logger.warning(
                "Sync-драйвер для БД '%s' недоступен (%s); sync_engine=None. "
                "Async-путь продолжит работу; durable APScheduler jobstore "
                "будет заменён на memory.",
                self.name,
                exc,
            )
            self.sync_engine = None
            self.sync_session_maker = None

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

    def get_sync_engine(self) -> Engine | None:
        """Возвращает синхронный engine или ``None`` (Wave F.3 async-first).

        Sync-engine может быть ``None``, если sync-драйвер не установлен;
        вызывающие должны иметь fallback (например, memory jobstore).
        """
        return self.sync_engine

    async def dispose_sync(self) -> None:
        """
        Закрывает синхронные соединения (no-op если sync_engine is None).
        """
        if self.sync_engine is None:
            return
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


@lru_cache(maxsize=1)
def get_db_initializer() -> "DatabaseInitializer":
    """Lazy singleton ``DatabaseInitializer`` для main-БД (Wave 6.1)."""
    return DatabaseInitializer(settings=settings.database, name="main")


@lru_cache(maxsize=1)
def get_external_db_registry() -> "ExternalDatabaseRegistry":
    """Lazy singleton реестра внешних БД (Wave 6.1)."""
    return ExternalDatabaseRegistry(configs=settings.external_databases.profiles)


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat импортов (Wave 6.1)."""
    if name == "db_initializer":
        return get_db_initializer()
    if name == "external_db_registry":
        return get_external_db_registry()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
