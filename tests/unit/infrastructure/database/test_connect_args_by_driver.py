"""ADR-0381 — driver-specific ``connect_args`` и пул SQLite.

Дефекты волны 16 (кластер X2):

1. **psycopg3-async сломан.** ``DatabaseInitializer._get_connect_args``
   для async-движка всегда передавал опции asyncpg (``command_timeout`` /
   ``timeout``) → ``psycopg.ProgrammingError: invalid connection option
   "command_timeout"``. psycopg3 — libpq-драйвер: у него ``connect_timeout``
   и ``options='-c statement_timeout=...'``.
2. **SQLite игнорирует настройки пула.** ``_engine_kwargs`` скипает
   ``pool_size``/``max_overflow``/``pool_timeout`` для SQLite: у
   ``:memory:`` SQLAlchemy использует ``StaticPool``, который эти параметры
   не принимает (``TypeError``). Для файловой БД пул не настраивается
   проектом — фиксируется осознанно (ADR-0381).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.enums.database import DatabaseTypeChoices
from src.backend.infrastructure.database.database.initializer import DatabaseInitializer


def _pg_settings(async_driver: str, sync_driver: str) -> DatabaseConnectionSettings:
    """PostgreSQL-настройки с заданной парой драйверов."""
    return DatabaseConnectionSettings(
        type=DatabaseTypeChoices.postgresql,
        host="localhost",
        port=5432,
        name="appdb",
        username="user",
        password="secret",  # noqa: S106 — тестовые настройки, без реальной БД
        async_driver=async_driver,
        sync_driver=sync_driver,
        ssl_mode=None,
        ca_bundle=None,
        pool_size=1,
        max_overflow=1,
        pool_recycle=60,
        pool_timeout=10,
        connect_timeout=5,
        command_timeout=7,
        max_retries=1,
        circuit_breaker_max_failures=3,
        circuit_breaker_reset_timeout=30,
        slow_query_threshold=1.0,
    )


def _sqlite_settings(path: str) -> DatabaseConnectionSettings:
    """SQLite-настройки (сетевые поля игнорируются)."""
    return DatabaseConnectionSettings(
        type=DatabaseTypeChoices.sqlite,
        path=path,
        host="",
        port=0,
        name="",
        username="",
        password="",
        ssl_mode=None,
        ca_bundle=None,
        pool_size=5,
        max_overflow=5,
        pool_recycle=60,
        pool_timeout=10,
        connect_timeout=5,
        command_timeout=7,
        max_retries=1,
        circuit_breaker_max_failures=3,
        circuit_breaker_reset_timeout=30,
        slow_query_threshold=1.0,
    )


def _connect_args(settings: Any, *, is_async: bool) -> dict[str, Any]:
    """Достаёт ``connect_args`` из инициализатора без создания engine."""
    initializer = DatabaseInitializer.__new__(DatabaseInitializer)
    initializer.settings = settings
    return initializer._get_connect_args(is_async=is_async)


@pytest.mark.unit
class TestConnectArgsPerDriver:
    """Опции подключения — по имени драйвера, а не по режиму engine."""

    def test_asyncpg_keeps_asyncpg_options(self) -> None:
        """asyncpg: ``command_timeout`` + ``timeout`` — его родные опции."""
        args = _connect_args(_pg_settings("asyncpg", "psycopg"), is_async=True)

        assert args["command_timeout"] == 7
        assert args["timeout"] == 5

    def test_psycopg_async_has_no_asyncpg_options(self) -> None:
        """psycopg (async) не принимает ``command_timeout``/``timeout``.

        Регрессия: psycopg3 отвечал
        ``ProgrammingError: invalid connection option "command_timeout"``.
        """
        args = _connect_args(_pg_settings("psycopg", "psycopg"), is_async=True)

        assert "command_timeout" not in args
        assert "timeout" not in args
        assert args["connect_timeout"] == 5
        assert args["options"] == "-c statement_timeout=7000"

    def test_psycopg_sync_has_no_asyncpg_options(self) -> None:
        """Sync-путь с psycopg — те же libpq-опции."""
        args = _connect_args(_pg_settings("asyncpg", "psycopg"), is_async=False)

        assert "command_timeout" not in args
        assert "timeout" not in args
        assert args["connect_timeout"] == 5
        assert args["options"] == "-c statement_timeout=7000"

    def test_psycopg_async_engine_accepts_connect_args(self) -> None:
        """``create_async_engine`` с psycopg принимает эти connect_args.

        Проверяем ровно то, что уходило в продакшен: набор опций, который
        SQLAlchemy передаст драйверу при установке соединения.
        """
        from sqlalchemy.ext.asyncio import create_async_engine

        settings = _pg_settings("psycopg", "psycopg")
        engine = create_async_engine(
            url=settings.async_connection_url,
            connect_args=_connect_args(settings, is_async=True),
        )
        assert engine is not None
        assert engine.pool is not None


@pytest.mark.unit
class TestSqlitePoolSettings:
    """SQLite: параметры пула не применяются (StaticPool их не принимает)."""

    def test_sqlite_engine_kwargs_have_no_pool_settings(self) -> None:
        """Для SQLite в ``_engine_kwargs`` нет pool_* — осознанное решение."""
        initializer = DatabaseInitializer.__new__(DatabaseInitializer)
        initializer.settings = _sqlite_settings(":memory:")

        kwargs = initializer._engine_kwargs(is_async=True)

        for key in (
            "pool_size",
            "max_overflow",
            "pool_recycle",
            "pool_timeout",
            "pool_pre_ping",
            "pool_use_lifo",
        ):
            assert key not in kwargs, f"SQLite не должен получать {key}"

    def test_sqlite_memory_engine_is_creatable(self) -> None:
        """``:memory:`` (StaticPool) создаётся без pool-параметров."""
        from sqlalchemy.ext.asyncio import create_async_engine

        settings = _sqlite_settings(":memory:")
        initializer = DatabaseInitializer.__new__(DatabaseInitializer)
        initializer.settings = settings

        engine = create_async_engine(
            url=settings.async_connection_url,
            **initializer._engine_kwargs(is_async=True),
        )
        assert engine.pool.__class__.__name__ == "StaticPool"

    def test_postgres_engine_kwargs_keep_pool_settings(self) -> None:
        """Для PostgreSQL pool-параметры сохраняются (регрессия)."""
        initializer = DatabaseInitializer.__new__(DatabaseInitializer)
        initializer.settings = _pg_settings("asyncpg", "psycopg")

        kwargs = initializer._engine_kwargs(is_async=True)

        assert kwargs["pool_size"] == 1
        assert kwargs["max_overflow"] == 1
        assert kwargs["pool_recycle"] == 60
        assert kwargs["pool_timeout"] == 10
