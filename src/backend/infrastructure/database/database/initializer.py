from __future__ import annotations

import ssl
from typing import Any

from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.db_drivers import DatabaseDriverError
from src.backend.core.config.external_databases import (
    ExternalDatabaseConnectionSettings,
)
from src.backend.core.enums.database import DatabaseTypeChoices
from src.backend.core.errors import DatabaseError
from src.backend.core.logging import get_logger
from src.backend.infrastructure.database.database.bundle import DatabaseBundle
from src.backend.infrastructure.database.listeners import DatabaseListener

db_logger = get_logger("database")


type DatabaseSettings = DatabaseConnectionSettings | ExternalDatabaseConnectionSettings


def _reveal_dsn(value: str | SecretStr | None) -> str | None:
    """Возвращает рабочее значение DSN (SecretStr → plain str).

    Main-БД типизирует ``replica_dsn`` как ``SecretStr`` (ADR-0381), внешний
    контур — как обычную строку. Движок реплики должен получить настоящий
    DSN с паролем; маскирование применяется только в дампах модели.
    """
    if value is None:
        return None
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value


class DatabaseInitializer:
    """Универсальный инициализатор подключения к БД.

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

        # S11 K2 W2: опциональная read-replica. ``replica_dsn`` определён
        # в :class:`DatabaseConnectionSettings`; для external БД поля нет
        # → ``getattr`` отдаёт ``None`` и replica-роутинг выключен.
        # ADR-0381: DSN реплики — секрет (SecretStr); движок получает
        # рабочее (незамаскированное) значение, маскирование живёт только
        # в дампах модели.
        self.replica_engine: AsyncEngine | None = None
        self.replica_session_maker: async_sessionmaker[AsyncSession] | None = None
        replica_url = _reveal_dsn(getattr(self.settings, "replica_dsn", None))
        if replica_url:
            self.replica_engine = create_async_engine(
                url=replica_url, **self._engine_kwargs(is_async=True)
            )
            self.replica_session_maker = async_sessionmaker(
                bind=self.replica_engine, autoflush=False, expire_on_commit=False
            )

        # K3 W1: OTel asyncpg auto-instrumentation под default-OFF feature-flag.
        # Однократный вызов — внутренний guard _ASYNCPG_INSTRUMENTED защищает от
        # повторного instrument() при создании нескольких DatabaseInitializer.
        try:
            from src.backend.infrastructure.observability.otel_auto import (
                instrument_asyncpg_if_enabled,
            )

            instrument_asyncpg_if_enabled()
        except Exception as exc:
            self.logger.debug("OTel asyncpg hook пропущен: %s", exc)

        # Wave F.3: async-first. Sync-engine опционален — если sync-драйвер
        # (psycopg/oracledb/pysqlite) не установлен, не валим старт; вместо
        # этого пишем warning и оставляем None. Потребители (APScheduler
        # SQLAlchemyJobStore) обязаны иметь fallback.
        # Wave 13 Q9: DatabaseDriverError — драйвер не объявлен в проекте
        # либо не установлен (core/config/db_drivers.py); тот же контракт
        # graceful-degradation, но с понятным сообщением.
        self.sync_engine: Engine | None
        self.sync_session_maker: sessionmaker | None
        try:
            self.sync_engine = self._create_sync_engine()
            self.sync_session_maker = sessionmaker(
                bind=self.sync_engine, autoflush=False, expire_on_commit=False
            )
        except (ModuleNotFoundError, DatabaseDriverError) as exc:
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

        # S21 W1: RLS SET LOCAL app.tenant_id listener (default-OFF).
        # Активируется get_feature_flag_service().is_enabled("rls_postgres_enforce") + dialect=postgresql.
        try:
            from src.backend.infrastructure.database.rls_listener import (
                install_rls_tenant_listener,
            )

            install_rls_tenant_listener(self.async_engine)
        except Exception as exc:
            self.logger.debug("RLS tenant listener пропущен: %s", exc)

    def as_bundle(self) -> DatabaseBundle:
        """Возвращает единый контейнер инфраструктурных объектов."""
        return DatabaseBundle(
            name=self.name,
            settings=self.settings,
            async_engine=self.async_engine,
            async_session_maker=self.async_session_maker,
            sync_engine=self.sync_engine,
            sync_session_maker=self.sync_session_maker,
            replica_engine=self.replica_engine,
            replica_session_maker=self.replica_session_maker,
        )

    def _engine_kwargs(self, *, is_async: bool) -> dict[str, Any]:
        """Базовые kwargs для create_engine / create_async_engine.

        Для SQLite pool-параметры **не применяются** (ADR-0381): у
        ``:memory:`` SQLAlchemy использует ``StaticPool``, который не
        принимает ``pool_size``/``max_overflow``/``pool_timeout``
        (``TypeError``), а пул файловой SQLite-БД блокирует записи на
        уровне файла. Значения ``pool_size``/``max_overflow``/``pool_recycle``
        из конфигурации к SQLite не применяются намеренно.
        """
        kwargs: dict[str, Any] = {
            "echo": self.settings.echo,
            # connect_args зависят от драйвера: asyncpg и psycopg (v3)
            # имеют РАЗНЫЕ имена таймаут-опций (найдено prod-drill
            # 2026-09-29: sync-драйвер отвергает asyncpg-овский
            # command_timeout как «invalid connection option»).
            "connect_args": self._get_connect_args(is_async=is_async),
        }
        if self.settings.type != DatabaseTypeChoices.sqlite:
            kwargs.update(
                {
                    "pool_size": self.settings.pool_size,
                    "max_overflow": self.settings.max_overflow,
                    "pool_recycle": self.settings.pool_recycle,
                    "pool_timeout": self.settings.pool_timeout,
                    # Cycle 172 (HIGH-12): значение было захардкожено
                    # (``True``), поле ``pool_pre_ping`` в конфиге и в
                    # ``config_profiles/prod.yml`` не читалось — настройка
                    # была мёртвой. Теперь берётся из настроек.
                    "pool_pre_ping": self.settings.pool_pre_ping,
                    "pool_use_lifo": self.settings.pool_use_lifo,
                }
            )
        return kwargs

    def _create_async_engine(self) -> AsyncEngine:
        """Создаёт и настраивает асинхронный engine SQLAlchemy."""
        return create_async_engine(
            url=self.settings.async_connection_url,  # type: ignore[arg-type]  # R2.MYPY: Callable[[],str] → str|URL
            **self._engine_kwargs(is_async=True),
        )

    def _create_sync_engine(self) -> Engine:
        """Создаёт и настраивает синхронный engine SQLAlchemy."""
        return create_engine(  # type: ignore[call-overload]
            url=self.settings.sync_connection_url, **self._engine_kwargs(is_async=False)
        )

    def _get_connect_args(self, *, is_async: bool) -> dict[str, Any]:
        """Генерирует driver-level параметры подключения.

        Опции зависят от **драйвера**, а не от режима engine (ADR-0381):

        * ``asyncpg`` — ``command_timeout`` / ``timeout`` (секунды);
        * ``psycopg`` (v3, libpq) — ``connect_timeout`` (секунды) и
          statement_timeout через ``options='-c statement_timeout=...'``.

        Раньше ветка выбиралась по ``is_async``, из-за чего async-движок с
        драйвером psycopg получал asyncpg-опции и падал с
        ``psycopg.ProgrammingError: invalid connection option
        "command_timeout"``.
        """
        connect_args: dict[str, Any] = {}

        driver = self.settings.async_driver if is_async else self.settings.sync_driver

        if self.settings.type == DatabaseTypeChoices.postgresql:
            if driver == "asyncpg":
                connect_args.update(
                    {
                        "command_timeout": self.settings.command_timeout,
                        "timeout": self.settings.connect_timeout,
                    }
                )
            else:
                # psycopg (v3) — libpq-драйвер: своих опций asyncpg не знает.
                connect_args["connect_timeout"] = self.settings.connect_timeout
                if self.settings.command_timeout:
                    connect_args["options"] = (
                        f"-c statement_timeout={int(self.settings.command_timeout) * 1000}"
                    )

            # Cycle 172 (CRITICAL-09): TLS определялся **исключительно** по
            # ``ca_bundle``, поэтому ``ssl_mode: "require"`` в prod.yml при
            # ``ca_bundle: null`` не давал шифрования — соединение с
            # production-БД уходило открытым. Теперь ``ssl_mode`` honoured:
            #
            # * ``disable`` / ``allow`` → TLS выключен явно;
            # * ``prefer`` / ``require`` / ``verify-ca`` / ``verify-full``
            #   → TLS с обязательной проверкой сертификата.
            #
            # Два сознательных отклонения от libpq, оба в сторону строгости —
            # потому что проект запрещает ``ssl.CERT_NONE`` /
            # ``check_hostname=False`` (CLAUDE.md, V1 Security Constraints):
            #
            # 1. В libpq ``require`` = «шифровать, сертификат НЕ проверять».
            #    Здесь ``require`` проверяет сертификат, как ``verify-ca``.
            # 2. В libpq ``prefer`` = «попробовать TLS, при неудаче молча уйти
            #    в plaintext». Этот молчаливый fallback не реализован: вместо
            #    него ``prefer`` включает TLS и пишет warning.
            #
            # Следствие для эксплуатации: если БД использует самоподписанный
            # сертификат, соединение будет падать. Это правильное поведение —
            # оператор задаёт ``ca_bundle`` либо явно выбирает ``disable``,
            # вместо того чтобы молча получать незашифрованное соединение.
            ssl_mode = (self.settings.ssl_mode or "").strip().lower()
            if ssl_mode and ssl_mode not in ("disable", "allow", "false", "off"):
                if ssl_mode not in ("prefer", "require", "verify-ca", "verify-full"):
                    raise ValueError(
                        f"Unsupported ssl_mode={ssl_mode!r} for "
                        f"{self.settings.type}; expected one of: disable, allow, "
                        "prefer, require, verify-ca, verify-full"
                    )
                if ssl_mode == "prefer":
                    db_logger.warning(
                        "database ssl_mode=prefer: TLS включён с проверкой "
                        "сертификата. libpq-fallback в plaintext намеренно не "
                        "реализован (CLAUDE.md V1 запрещает ssl.CERT_NONE). "
                        "Если БД без TLS — задайте ssl_mode=disable явно."
                    )
                if self.settings.ca_bundle:
                    connect_args["ssl"] = ssl.create_default_context(
                        cafile=self.settings.ca_bundle
                    )
                else:
                    # Системное хранилище CA: create_default_context без cafile.
                    connect_args["ssl"] = ssl.create_default_context()

        elif self.settings.type == DatabaseTypeChoices.oracle:
            connect_args.update({"tcp_connect_timeout": self.settings.connect_timeout})

        return connect_args

    async def initialize_async_pool(self) -> None:
        """Предварительно прогревает асинхронный пул соединений."""
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
        """Возвращает асинхронный engine."""
        return self.async_engine

    def get_sync_engine(self) -> Engine | None:
        """Возвращает синхронный engine или ``None`` (Wave F.3 async-first).

        Sync-engine может быть ``None``, если sync-драйвер не установлен;
        вызывающие должны иметь fallback (например, memory jobstore).
        """
        return self.sync_engine

    async def dispose_sync(self) -> None:
        """Закрывает синхронные соединения (no-op если sync_engine is None)."""
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
        """Закрывает асинхронные соединения."""
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
        """Закрывает все соединения с БД."""
        await self.dispose_sync()
        await self.dispose_async()
        if self.replica_engine is not None:
            try:
                await self.replica_engine.dispose()
            except (RuntimeError, OSError):
                self.logger.error(
                    "Ошибка закрытия replica engine",
                    extra={"db_name": self.name},
                    exc_info=True,
                )

    async def check_connection(self) -> bool:
        """Проверяет работоспособность подключения.

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
