"""ADR-0381 — fail-fast на несовместимых парах (тип СУБД, драйвер).

Дефект волны 16 (кластер X2 «Драйверы и DSN»): дефолтные PG-драйверы
(``asyncpg``/``psycopg``) применялись к MSSQL/MySQL → DSN вида
``mssql+asyncpg://`` → ``NoSuchModuleError`` внутри SQLAlchemy уже в
рантайме (после старта приложения).

Контракт:

* несовместимая пара (тип СУБД, драйвер) отвергается **до** сборки DSN
  понятной ``DatabaseDriverError`` (без ``NoSuchModuleError``);
* DB2 не поддерживается: диалект ``sqlalchemy.dialects.db2`` удалён в
  SQLAlchemy 2.0, драйвер ``ibm_db_sa`` не объявлен ни в одном extra;
* ClickHouse не поддерживается через SQLAlchemy DSN — у него отдельный
  клиент (``infrastructure/clients/storage/clickhouse.py``);
* валидные пары продолжают собирать DSN.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.db_drivers import DatabaseDriverError
from src.backend.core.enums.database import DatabaseTypeChoices


def _make_settings(**overrides: Any) -> DatabaseConnectionSettings:
    """Создаёт ``DatabaseConnectionSettings`` с валидными дефолтами.

    ``ssl_mode`` сбрасывается в ``None`` — в профиле ``dev`` он задан как
    ``"prefer"``, а ``validate_ssl`` отвергает SSL для non-PostgreSQL типов.
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


@pytest.mark.unit
class TestIncompatibleDriverPairRejected:
    """Несовместимая пара (тип, драйвер) → fail-fast, а не NoSuchModuleError."""

    def test_mssql_with_pg_default_async_driver_rejected(self) -> None:
        """MSSQL + дефолтный ``asyncpg`` → понятная ошибка до сборки DSN."""
        settings = _make_settings(
            type=DatabaseTypeChoices.mssql,
            port=1433,
            async_driver="asyncpg",
            sync_driver="pyodbc",
        )
        with pytest.raises(DatabaseDriverError) as exc_info:
            _ = settings.async_connection_url

        message = str(exc_info.value)
        assert "asyncpg" in message
        assert "mssql" in message
        assert "aioodbc" in message, "сообщение должно назвать допустимый драйвер"

    def test_mssql_with_pg_default_sync_driver_rejected(self) -> None:
        """MSSQL + дефолтный sync ``psycopg`` → та же ошибка."""
        settings = _make_settings(
            type=DatabaseTypeChoices.mssql,
            port=1433,
            async_driver="aioodbc",
            sync_driver="psycopg",
        )
        with pytest.raises(DatabaseDriverError) as exc_info:
            _ = settings.sync_connection_url

        message = str(exc_info.value)
        assert "psycopg" in message
        assert "pyodbc" in message

    def test_mysql_with_pg_default_async_driver_rejected(self) -> None:
        """MySQL + ``asyncpg`` → fail-fast (иначе ``mysql+asyncpg://``)."""
        settings = _make_settings(
            type=DatabaseTypeChoices.mysql,
            port=3306,
            async_driver="asyncpg",
            sync_driver="pymysql",
        )
        with pytest.raises(DatabaseDriverError) as exc_info:
            _ = settings.async_connection_url

        message = str(exc_info.value)
        assert "asyncpg" in message
        assert "mysql" in message
        assert "aiomysql" in message

    def test_mysql_with_asyncpg_sync_driver_rejected(self) -> None:
        """MySQL sync + ``psycopg`` → fail-fast."""
        settings = _make_settings(
            type=DatabaseTypeChoices.mysql,
            port=3306,
            async_driver="aiomysql",
            sync_driver="psycopg",
        )
        with pytest.raises(DatabaseDriverError):
            _ = settings.sync_connection_url

    def test_mssql_async_driver_cannot_be_sync_only(self) -> None:
        """``aioodbc`` — async-only диалект; для sync нужен ``pyodbc``."""
        settings = _make_settings(
            type=DatabaseTypeChoices.mssql,
            port=1433,
            async_driver="aioodbc",
            sync_driver="aioodbc",
        )
        with pytest.raises(DatabaseDriverError) as exc_info:
            _ = settings.sync_connection_url

        assert "pyodbc" in str(exc_info.value)


@pytest.mark.unit
class TestUnsupportedDbTypes:
    """Типы, недостижимые через SQLAlchemy DSN, отвергаются явно."""

    def test_db2_is_not_supported(self) -> None:
        """DB2: диалект удалён в SQLAlchemy 2.0 → fail-fast с объяснением."""
        settings = _make_settings(
            type=DatabaseTypeChoices.db2,
            port=50000,
            async_driver="ibm_db_sa",
            sync_driver="ibm_db_sa",
        )
        with pytest.raises(DatabaseDriverError) as exc_info:
            _ = settings.async_connection_url

        message = str(exc_info.value)
        assert "DB2" in message
        assert "не поддерживается" in message

    def test_db2_sync_dsn_also_rejected(self) -> None:
        """DB2 отвергается и на sync-пути."""
        settings = _make_settings(
            type=DatabaseTypeChoices.db2,
            port=50000,
            async_driver="ibm_db_sa",
            sync_driver="ibm_db_sa",
        )
        with pytest.raises(DatabaseDriverError):
            _ = settings.sync_connection_url

    def test_clickhouse_is_not_a_sqlalchemy_target(self) -> None:
        """ClickHouse: ``clickhouse://`` невалиден для SQLAlchemy → fail-fast."""
        settings = _make_settings(
            type=DatabaseTypeChoices.clickhouse,
            port=8123,
            async_driver="clickhouse_connect",
            sync_driver="clickhouse_connect",
        )
        with pytest.raises(DatabaseDriverError) as exc_info:
            _ = settings.async_connection_url

        message = str(exc_info.value)
        assert "ClickHouse" in message
        assert "clickhouse.py" in message, "сообщение должно указать клиент"


@pytest.mark.unit
class TestCompatiblePairsStillBuild:
    """Валидные пары продолжают собирать DSN."""

    def test_mssql_odbc_pair(self) -> None:
        """MSSQL: ``aioodbc`` (async) + ``pyodbc`` (sync)."""
        settings = _make_settings(
            type=DatabaseTypeChoices.mssql,
            port=1433,
            async_driver="aioodbc",
            sync_driver="pyodbc",
        )
        assert settings.async_connection_url.startswith("mssql+aioodbc://")
        assert settings.sync_connection_url.startswith("mssql+pyodbc://")

    def test_mysql_pair(self) -> None:
        """MySQL: ``aiomysql`` (async) + ``pymysql`` (sync)."""
        settings = _make_settings(
            type=DatabaseTypeChoices.mysql,
            port=3306,
            async_driver="aiomysql",
            sync_driver="pymysql",
        )
        assert settings.async_connection_url.startswith("mysql+aiomysql://")
        assert settings.sync_connection_url.startswith("mysql+pymysql://")

    def test_postgresql_psycopg_async_allowed(self) -> None:
        """PostgreSQL: ``psycopg`` (psycopg3) валиден и для async-движка."""
        settings = _make_settings(
            type=DatabaseTypeChoices.postgresql,
            async_driver="psycopg",
            sync_driver="psycopg",
        )
        assert settings.async_connection_url.startswith("postgresql+psycopg://")
        assert settings.sync_connection_url.startswith("postgresql+psycopg://")

    def test_oracle_pair(self) -> None:
        """Oracle: ``oracledb`` в обоих режимах."""
        settings = _make_settings(
            type=DatabaseTypeChoices.oracle,
            port=1521,
            async_driver="oracledb",
            sync_driver="oracledb",
        )
        assert settings.async_connection_url.startswith("oracle+oracledb://")
