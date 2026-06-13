"""S104 W3 — tests для DSN builder MSSQL / MySQL / DB2 (DEEP-RESEARCH D19).

Verifies DSN format для новых database types в ``DatabaseConnectionSettings``.

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
        "sync_driver": "psycopg2",
        "ssl_mode": None,
        "ca_bundle": None,
    }
    defaults.update(overrides)
    return DatabaseConnectionSettings(**defaults)


# ──────────────────────────────────────────────────────────────────────
# Enum
# ──────────────────────────────────────────────────────────────────────


def test_database_type_choices_has_new_types() -> None:
    """``DatabaseTypeChoices`` имеет mssql / mysql / db2 (S104 W3)."""
    assert DatabaseTypeChoices.mssql.value == "mssql"
    assert DatabaseTypeChoices.mysql.value == "mysql"
    assert DatabaseTypeChoices.db2.value == "db2"


# ──────────────────────────────────────────────────────────────────────
# MSSQL
# ──────────────────────────────────────────────────────────────────────


def test_mssql_dsn_format_sync() -> None:
    """MSSQL sync DSN: ``mssql+pyodbc://...?driver=ODBC+Driver+17+for+SQL+Server``."""
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
    assert dsn.startswith("mssql+pyodbc://")
    assert "sa:P@ssw0rd@mssql.example.com:1433/mydb" in dsn
    assert "ODBC+Driver+17+for+SQL+Server" in dsn


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
    """DB2 sync DSN: ``db2+ibm_db_sa://``."""
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
    dsn = s.sync_connection_url
    assert dsn.startswith("db2+ibm_db_sa://")
    assert "db2inst1:pwd@db2.example.com:50000/mydb" in dsn


def test_db2_dsn_format_async() -> None:
    """DB2 async DSN: ``db2+ibm_db_sa://`` (один драйвер на sync/async)."""
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
    dsn = s.async_connection_url
    assert dsn.startswith("db2+ibm_db_sa://")
    assert "db2inst1:pwd@db2.local:50000/db1" in dsn


# ──────────────────────────────────────────────────────────────────────
# Регрессионные проверки (existing types не сломаны)
# ──────────────────────────────────────────────────────────────────────


def test_postgres_dsn_still_works() -> None:
    """PostgreSQL DSN НЕ regression (S104 W3 additive only)."""
    s = _make_settings(
        type=DatabaseTypeChoices.postgresql,
        async_driver="asyncpg",
        sync_driver="psycopg2",
    )
    dsn = s.async_connection_url
    assert dsn.startswith("postgresql+asyncpg://")


def test_oracle_dsn_still_works() -> None:
    """Oracle DSN НЕ regression."""
    s = _make_settings(
        type=DatabaseTypeChoices.oracle,
        host="oracle.example.com",
        port=1521,
        name="ORCLPDB1",
        async_driver="oracledb",
        sync_driver="cx_Oracle",
    )
    dsn = s.sync_connection_url
    assert dsn.startswith("oracle+cx_Oracle://")
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
