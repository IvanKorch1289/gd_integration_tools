"""S104 W3 — tests для DSN builder MSSQL / MySQL / DB2 (DEEP-RESEARCH D19).

Verifies DSN format для новых database types в ``DatabaseConnectionSettings``.

Wave 13 Q9: DSN-конструктор теперь fail-fast на драйверах, которые не
объявлены ни в одном extra проекта (``core/config/db_drivers.py``):

* ``aioodbc`` (MSSQL async), ``aiomysql``/``pymysql`` (MySQL),
  ``oracledb`` (Oracle) объявлены в extra ``db_drivers`` → DSN строится.

ADR-0381 (волна 16, кластер X2):

* проверяется **пара** (тип СУБД, драйвер): MSSQL/MySQL больше не
  наследуют PG-драйверы (``asyncpg``) → невалидный ``mssql+asyncpg://``;
* DB2 недостижим (диалект ``sqlalchemy.dialects.db2`` удалён в SQLAlchemy
  2.0, ``ibm_db_sa`` не объявлен) → fail-fast с объяснением.

Замечания по тестированию:
    * В активном профиле ``dev`` (``config_profiles/dev.yml``) блок
      ``database:`` содержит ``ssl_mode: "prefer"``. Поскольку модель
      auto-loads YAML, мы обязаны явно передать ``ssl_mode=None`` при
      смене ``type`` на не-PostgreSQL СУБД — иначе валидатор
      ``validate_ssl`` бросает ``ValueError``.
    * Поля пула (``pool_size``, ``max_overflow``, ``pool_recycle`` и т.д.)
      берутся из YAML и не переопределяются в тестах.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.db_drivers import DatabaseDriverError
from src.backend.core.enums.database import DatabaseTypeChoices

# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


def _make_settings(**overrides: Any) -> DatabaseConnectionSettings:
    """Создаёт ``DatabaseConnectionSettings`` с валидными дефолтами.

    Переопределения: ``type``, ``username``, ``password``, ``host``,
    ``port``, ``name``, ``async_driver``, ``sync_driver``. SSL
    принудительно сбрасывается (``ssl_mode=None``) — иначе
    ``validate_ssl`` падает на non-PostgreSQL типах из-за
    ``ssl_mode: "prefer"`` в ``dev.yml``.
    """
    defaults: dict[str, Any] = {
        "type": DatabaseTypeChoices.postgresql,
        "username": "user",
        "password": "pwd",
        "host": "localhost",
        "port": 5432,
        "name": "mydb",
        "async_driver": "asyncpg",
        "sync_driver": "psycopg",
        "ssl_mode": None,
        "ca_bundle": None,
    }
    defaults.update(overrides)
    return DatabaseConnectionSettings(**defaults)


# ──────────────────────────────────────────────────────────────────────
# Enum
# ──────────────────────────────────────────────────────────────────────


def test_database_type_choices_has_new_types() -> None:
    """``DatabaseTypeChoices`` имеет mssql / mysql / db2 (S104 W3).

    ADR-0381: значение ``db2`` остаётся в enum (на него ссылается внешний
    контур), но тип **недостижим** через SQLAlchemy DSN — отвергается
    fail-fast с понятным сообщением.
    """
    assert DatabaseTypeChoices.mssql.value == "mssql"
    assert DatabaseTypeChoices.mysql.value == "mysql"
    assert DatabaseTypeChoices.db2.value == "db2"


# ──────────────────────────────────────────────────────────────────────
# MSSQL
# ──────────────────────────────────────────────────────────────────────


def test_mssql_dsn_format_sync() -> None:
    """MSSQL sync: ``pyodbc`` объявлен в extra ``db_drivers`` → DSN собирается.

    Wave 13 Q9: драйвер не был объявлен ни в одном extra → конструктор
    отвергал его понятным сообщением вместо позднего ``ModuleNotFoundError``.
    Wave 13 Q2 (согласовано с владельцем): ``pyodbc`` объявлен в
    ``db_drivers`` — DSN теперь собирается; пароль URL-кодируется
    (``quote_plus``, коммит 8a0933cd3).
    """
    s = _make_settings(
        type=DatabaseTypeChoices.mssql,
        username="sa",
        password="P@ssw0rd",
        host="mssql.example.com",
        port=1433,
        name="mydb",
        async_driver="aioodbc",
        sync_driver="pyodbc",
    )
    dsn = s.sync_connection_url
    assert dsn.startswith("mssql+pyodbc://sa:P%40ssw0rd@mssql.example.com:1433/mydb")


def test_mssql_dsn_format_async() -> None:
    """MSSQL async DSN: ``mssql+aioodbc://``."""
    s = _make_settings(
        type=DatabaseTypeChoices.mssql,
        username="sa",
        password="pwd",
        host="mssql.local",
        port=1433,
        name="db1",
        async_driver="aioodbc",
        sync_driver="pyodbc",
    )
    dsn = s.async_connection_url
    assert dsn.startswith("mssql+aioodbc://")
    assert "sa:pwd@mssql.local:1433/db1" in dsn


# ──────────────────────────────────────────────────────────────────────
# MySQL
# ──────────────────────────────────────────────────────────────────────


def test_mysql_dsn_format_sync() -> None:
    """MySQL sync DSN: ``mysql+pymysql://``."""
    s = _make_settings(
        type=DatabaseTypeChoices.mysql,
        username="root",
        password="pwd",
        host="mysql.example.com",
        port=3306,
        name="mydb",
        async_driver="aiomysql",
        sync_driver="pymysql",
    )
    dsn = s.sync_connection_url
    assert dsn.startswith("mysql+pymysql://")
    assert "root:pwd@mysql.example.com:3306/mydb" in dsn


def test_mysql_dsn_format_async() -> None:
    """MySQL async DSN: ``mysql+aiomysql://``."""
    s = _make_settings(
        type=DatabaseTypeChoices.mysql,
        username="root",
        password="pwd",
        host="mysql.local",
        port=3306,
        name="db1",
        async_driver="aiomysql",
        sync_driver="pymysql",
    )
    dsn = s.async_connection_url
    assert dsn.startswith("mysql+aiomysql://")
    assert "root:pwd@mysql.local:3306/db1" in dsn


# ──────────────────────────────────────────────────────────────────────
# DB2
# ──────────────────────────────────────────────────────────────────────


def test_db2_dsn_format_sync() -> None:
    """DB2 sync: тип недостижим через SQLAlchemy DSN → fail-fast (ADR-0381).

    Диалект ``sqlalchemy.dialects.db2`` удалён в SQLAlchemy 2.0, драйвер
    ``ibm_db_sa`` не объявлен ни в одном extra.
    """
    s = _make_settings(
        type=DatabaseTypeChoices.db2,
        username="db2inst1",
        password="pwd",
        host="db2.example.com",
        port=50000,
        name="mydb",
        async_driver="ibm_db_sa",
        sync_driver="ibm_db_sa",
    )
    with pytest.raises(DatabaseDriverError) as exc_info:
        _ = s.sync_connection_url
    assert "DB2" in str(exc_info.value)


def test_db2_dsn_format_async() -> None:
    """DB2 async: тот же fail-fast для async-драйвера."""
    s = _make_settings(
        type=DatabaseTypeChoices.db2,
        username="db2inst1",
        password="pwd",
        host="db2.local",
        port=50000,
        name="db1",
        async_driver="ibm_db_sa",
        sync_driver="ibm_db_sa",
    )
    with pytest.raises(DatabaseDriverError):
        _ = s.async_connection_url


# ──────────────────────────────────────────────────────────────────────
# Регрессионные проверки (existing types не сломаны)
# ──────────────────────────────────────────────────────────────────────


def test_postgres_dsn_still_works() -> None:
    """PostgreSQL DSN НЕ regression (S104 W3 additive only)."""
    s = _make_settings(
        type=DatabaseTypeChoices.postgresql,
        async_driver="asyncpg",
        sync_driver="psycopg",
    )
    dsn = s.async_connection_url
    assert dsn.startswith("postgresql+asyncpg://")


def test_oracle_dsn_still_works() -> None:
    """Oracle DSN НЕ regression.

    Wave 13 Q9: используется ``oracledb`` (объявлен в extra ``db_drivers``),
    а не legacy ``cx_Oracle`` — тот в проекте не объявлен.
    """
    s = _make_settings(
        type=DatabaseTypeChoices.oracle,
        host="oracle.example.com",
        port=1521,
        name="ORCLPDB1",
        async_driver="oracledb",
        sync_driver="oracledb",
    )
    dsn = s.sync_connection_url
    assert dsn.startswith("oracle+oracledb://")
    assert "service_name=ORCLPDB1" in dsn


def test_sqlite_dsn_still_works() -> None:
    """SQLite DSN НЕ regression."""
    # SQLite не использует сетевые параметры, но модель требует все
    # обязательные поля (pool_size, max_overflow и т.д.) — берём из
    # YAML/дефолтов через helper.
    s = _make_settings(
        type=DatabaseTypeChoices.sqlite,
        path="/tmp/test.db",
        username="",
        password="",
        host="",
        port=0,
        name="",
    )
    dsn = s.sync_connection_url
    assert dsn.startswith("sqlite+pysqlite:///")
    assert "/tmp/test.db" in dsn
