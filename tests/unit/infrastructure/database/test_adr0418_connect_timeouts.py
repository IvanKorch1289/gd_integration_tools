"""ADR-0418 — таймауты подключения и запроса для MySQL / MSSQL / Oracle.

Дефект волны 24 (кластер F3, medium): ``DatabaseInitializer.
_get_connect_args`` обрабатывал только PostgreSQL и Oracle (и у Oracle — только
connect-таймаут). Для MySQL и MSSQL обе опции конфигурации
(``connect_timeout`` / ``command_timeout``) были **мёртвы**:

    mysql async={}
    oracle async={'tcp_connect_timeout': 10}   # statement-timeout нет

Контракт фикса:

* MySQL (aiomysql/pymysql) — ``connect_timeout`` + ``init_command`` с
  ``SET SESSION max_execution_time``;
* MSSQL (aioodbc/pyodbc) — ``timeout`` (ODBC ``SQL_ATTR_LOGIN_TIMEOUT``);
* Oracle (oracledb) — ``tcp_connect_timeout`` + ``call_timeout``
  (свойство соединения — применяется через ``connect``-event, потому что
  ``oracledb.connect()`` не принимает этот параметр).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.enums.database import DatabaseTypeChoices
from src.backend.infrastructure.database.database.initializer import DatabaseInitializer

pytestmark = pytest.mark.unit


def _settings(
    db_type: DatabaseTypeChoices, *, async_driver: str, sync_driver: str
) -> DatabaseConnectionSettings:
    """Настройки подключения с заданной парой драйверов."""
    return DatabaseConnectionSettings(
        type=db_type,
        host="db.example.com",
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
        connect_timeout=11,
        command_timeout=22,
        max_retries=1,
        circuit_breaker_max_failures=3,
        circuit_breaker_reset_timeout=30,
        slow_query_threshold=1.0,
    )


def _connect_args(settings: Any, *, is_async: bool) -> dict[str, Any]:
    """Достаёт ``connect_args`` из инициализатора без создания engine."""
    initializer = DatabaseInitializer.__new__(DatabaseInitializer)
    initializer.settings = settings
    initializer.name = "probe"
    return initializer._get_connect_args(is_async=is_async)


def test_mysql_has_connect_timeout() -> None:
    """MySQL: ``connect_timeout`` доходит до драйвера (aiomysql)."""
    settings = _settings(
        DatabaseTypeChoices.mysql, async_driver="aiomysql", sync_driver="pymysql"
    )

    args = _connect_args(settings, is_async=True)

    assert args["connect_timeout"] == 11


def test_mysql_has_statement_timeout() -> None:
    """MySQL: лимит времени запроса — ``max_execution_time`` (мс)."""
    settings = _settings(
        DatabaseTypeChoices.mysql, async_driver="aiomysql", sync_driver="pymysql"
    )

    args = _connect_args(settings, is_async=True)

    assert "max_execution_time=22000" in args["init_command"]


def test_mysql_sync_driver_has_same_timeouts() -> None:
    """Sync-ветка MySQL (pymysql) — те же опции."""
    settings = _settings(
        DatabaseTypeChoices.mysql, async_driver="aiomysql", sync_driver="pymysql"
    )

    args = _connect_args(settings, is_async=False)

    assert args["connect_timeout"] == 11
    assert "max_execution_time=22000" in args["init_command"]


def test_mssql_has_odbc_login_timeout() -> None:
    """MSSQL: ``timeout`` — ODBC SQL_ATTR_LOGIN_TIMEOUT."""
    settings = _settings(
        DatabaseTypeChoices.mssql, async_driver="aioodbc", sync_driver="pyodbc"
    )

    args = _connect_args(settings, is_async=True)

    assert args["timeout"] == 11


def test_mssql_sync_driver_has_odbc_login_timeout() -> None:
    """Sync-ветка MSSQL (pyodbc) — тот же ODBC-таймаут."""
    settings = _settings(
        DatabaseTypeChoices.mssql, async_driver="aioodbc", sync_driver="pyodbc"
    )

    args = _connect_args(settings, is_async=False)

    assert args["timeout"] == 11


def test_oracle_has_connect_and_call_timeout() -> None:
    """Oracle: ``tcp_connect_timeout`` + ``call_timeout``."""
    settings = _settings(
        DatabaseTypeChoices.oracle, async_driver="oracledb", sync_driver="oracledb"
    )

    args = _connect_args(settings, is_async=True)

    assert args["tcp_connect_timeout"] == 11
    assert args["call_timeout"] == 22


def test_oracle_call_timeout_not_passed_to_driver_connect() -> None:
    """``call_timeout`` не уходит в ``connect()`` — oracledb его не примет.

    ``oracledb.connect()`` не имеет параметра ``call_timeout`` (TypeError),
    поэтому опция применяется к соединению через ``connect``-event.
    """
    settings = _settings(
        DatabaseTypeChoices.oracle, async_driver="oracledb", sync_driver="oracledb"
    )
    initializer = DatabaseInitializer.__new__(DatabaseInitializer)
    initializer.settings = settings
    initializer.name = "probe"

    kwargs = initializer._engine_kwargs(is_async=True)

    assert "call_timeout" not in kwargs["connect_args"]
    assert kwargs["connect_args"]["tcp_connect_timeout"] == 11


def test_oracle_call_timeout_applied_to_connection() -> None:
    """Post-connect опция выставляется на драйверном соединении."""
    settings = _settings(
        DatabaseTypeChoices.oracle, async_driver="oracledb", sync_driver="oracledb"
    )
    initializer = DatabaseInitializer.__new__(DatabaseInitializer)
    initializer.settings = settings
    initializer.name = "probe"

    class _FakeDbapiConnection:
        """Соединение-драйвер с настраиваемым ``call_timeout``."""

        def __init__(self) -> None:
            self.call_timeout: int | None = None

    connection = _FakeDbapiConnection()
    initializer._apply_post_connect(connection, {"call_timeout": 22})

    assert connection.call_timeout == 22


def test_oracle_post_connect_listener_registered_on_engine() -> None:
    """Для Oracle ``connect``-event регистрируется на движке."""
    from sqlalchemy import create_engine

    settings = _settings(
        DatabaseTypeChoices.oracle, async_driver="oracledb", sync_driver="oracledb"
    )
    initializer = DatabaseInitializer.__new__(DatabaseInitializer)
    initializer.settings = settings
    initializer.name = "probe"

    engine = create_engine("sqlite://")
    initializer._apply_post_connect_settings(engine, is_async=False)

    assert bool(engine.pool.dispatch.connect), "connect-event не зарегистрирован"
    engine.dispose()


def test_postgres_has_no_post_connect_settings() -> None:
    """Для PostgreSQL post-connect опций нет (всё уходит в ``connect()``)."""
    settings = _settings(
        DatabaseTypeChoices.postgresql, async_driver="asyncpg", sync_driver="psycopg"
    )
    initializer = DatabaseInitializer.__new__(DatabaseInitializer)
    initializer.settings = settings
    initializer.name = "probe"

    kwargs = initializer._engine_kwargs(is_async=True)

    assert "call_timeout" not in kwargs["connect_args"]


def test_postgres_behaviour_unchanged() -> None:
    """Регрессия: PostgreSQL-опции не изменились (asyncpg / psycopg)."""
    pg = _settings(
        DatabaseTypeChoices.postgresql, async_driver="asyncpg", sync_driver="psycopg"
    )

    asyncpg_args = _connect_args(pg, is_async=True)
    psycopg_args = _connect_args(pg, is_async=False)

    assert asyncpg_args["command_timeout"] == 22
    assert asyncpg_args["timeout"] == 11
    assert psycopg_args["connect_timeout"] == 11
    assert psycopg_args["options"] == "-c statement_timeout=22000"
