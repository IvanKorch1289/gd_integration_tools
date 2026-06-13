"""S104 W3 — tests для DSN builder MSSQL/MySQL/DB2.

Verifies DSN format для новых database types.
"""
from __future__ import annotations

import pytest


def test_database_type_choices_has_new_types() -> None:
    """``DatabaseTypeChoices`` имеет mssql / mysql / db2 (S104 W3)."""
    from src.backend.core.enums.database import DatabaseTypeChoices

    assert hasattr(DatabaseTypeChoices, "mssql")
    assert hasattr(DatabaseTypeChoices, "mysql")
    assert hasattr(DatabaseTypeChoices, "db2")
    assert DatabaseTypeChoices.mssql.value == "mssql"
    assert DatabaseTypeChoices.mysql.value == "mysql"
    assert DatabaseTypeChoices.db2.value == "db2"


def test_mssql_dsn_format_sync() -> None:
    """MSSQL sync DSN: ``mssql+pyodbc://...?driver=ODBC+Driver+17+for+SQL+Server``."""
    from src.backend.core.config.database import DatabaseSettings
    from src.backend.core.enums.database import DatabaseTypeChoices

    s = DatabaseSettings(
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
    from src.backend.core.config.database import DatabaseSettings
    from src.backend.core.enums.database import DatabaseTypeChoices

    s = DatabaseSettings(
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


def test_mysql_dsn_format_sync() -> None:
    """MySQL sync DSN: ``mysql+pymysql://``."""
    from src.backend.core.config.database import DatabaseSettings
    from src.backend.core.enums.database import DatabaseTypeChoices

    s = DatabaseSettings(
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
    from src.backend.core.config.database import DatabaseSettings
    from src.backend.core.enums.database import DatabaseTypeChoices

    s = DatabaseSettings(
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


def test_db2_dsn_format() -> None:
    """DB2 DSN: ``db2+ibm_db_sa://``."""
    from src.backend.core.config.database import DatabaseSettings
    from src.backend.core.enums.database import DatabaseTypeChoices

    s = DatabaseSettings(
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


def test_postgres_dsn_still_works() -> None:
    """PostgreSQL DSN НЕ regression (S104 W3 additive only)."""
    from src.backend.core.config.database import DatabaseSettings
    from src.backend.core.enums.database import DatabaseTypeChoices

    s = DatabaseSettings(
        type=DatabaseTypeChoices.postgresql,
        username="user",
        password="pwd",
        host="pg.example.com",
        port=5432,
        name="mydb",
        async_driver="asyncpg",
        sync_driver="psycopg2",
    )
    dsn = s.async_connection_url
    assert dsn.startswith("postgresql+asyncpg://")


def test_oracle_dsn_still_works() -> None:
    """Oracle DSN НЕ regression."""
    from src.backend.core.config.database import DatabaseSettings
    from src.backend.core.enums.database import DatabaseTypeChoices

    s = DatabaseSettings(
        type=DatabaseTypeChoices.oracle,
        username="system",
        password="pwd",
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
    from src.backend.core.config.database import DatabaseSettings
    from src.backend.core.enums.database import DatabaseTypeChoices

    s = DatabaseSettings(
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
