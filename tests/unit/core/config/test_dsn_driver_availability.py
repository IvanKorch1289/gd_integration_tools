"""Wave 13 Q9 — fail-fast валидация DSN-драйверов (core/config).

Контракт:

* дефолтный sync-драйвер PostgreSQL = ``psycopg`` (psycopg3: умеет и sync,
  и async; ``psycopg2`` в проекте отсутствует — нет ни в extras, ни в lock);
* DSN собирается как ``postgresql+psycopg://...``;
* драйвер, **не объявленный ни в одном extra** проекта, отвергается ДО
  сборки DSN с понятным сообщением (``DatabaseDriverError``), вместо
  ``ModuleNotFoundError`` в рантайме (например ``psycopg2``/``pyodbc``);
* драйвер, объявленный в extra, но не установленный в окружении, — тоже
  fail-fast: сообщение называет extra, который надо доустановить.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.db_drivers import (
    DB_DRIVER_DECLARATIONS,
    DatabaseDriverError,
)
from src.backend.core.enums.database import DatabaseTypeChoices

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _make_settings(**overrides: Any) -> DatabaseConnectionSettings:
    """Создаёт ``DatabaseConnectionSettings`` с валидными дефолтами.

    ``ssl_mode`` сбрасывается в ``None`` — в профиле ``dev`` он задан как
    ``"prefer"``, а ``validate_ssl`` отвергает SSL для не-PostgreSQL типов.
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
class TestSyncDriverDefault:
    """Дефолтный sync-драйвер PostgreSQL = ``psycopg`` (не ``psycopg2``)."""

    def test_field_default_is_psycopg(self) -> None:
        """Field-default ``sync_driver`` = ``psycopg``."""
        default = DatabaseConnectionSettings.model_fields["sync_driver"].default
        assert default == "psycopg"

    def test_base_profile_sync_driver_is_psycopg(self) -> None:
        """``config_profiles/base.yml`` объявляет ``sync_driver: psycopg``.

        YAML-loader имеет приоритет над Field-default, поэтому эффективное
        значение настроек берётся именно из профиля.
        """
        base = yaml.safe_load(
            (_REPO_ROOT / "config_profiles" / "base.yml").read_text(encoding="utf-8")
        )
        assert base["database"]["sync_driver"] == "psycopg"

    def test_psycopg2_is_not_declared_anywhere(self) -> None:
        """``psycopg2`` не остаётся в DSN-конструкторах конфигурации."""
        sources = (
            _REPO_ROOT / "src" / "backend" / "core" / "config" / "database.py",
            _REPO_ROOT
            / "src"
            / "backend"
            / "core"
            / "config"
            / "external_databases"
            / "item.py",
        )
        for source in sources:
            assert "psycopg2" not in source.read_text(encoding="utf-8"), (
                f"{source}: psycopg2 отсутствует в проекте — убери упоминание"
            )

    def test_sync_dsn_uses_psycopg(self) -> None:
        """Sync-DSN PostgreSQL = ``postgresql+psycopg://...``."""
        settings = _make_settings()
        dsn = settings.sync_connection_url
        assert dsn.startswith("postgresql+psycopg://")
        assert "user:pwd@localhost:5432/mydb" in dsn


@pytest.mark.unit
class TestUndeclaredDriverRejected:
    """Драйвер вне extras → понятная ошибка, а не ModuleNotFoundError."""

    def test_psycopg2_rejected_with_clear_message(self) -> None:
        """``psycopg2`` (нет ни в одном extra) → ``DatabaseDriverError``."""
        settings = _make_settings(sync_driver="psycopg2")
        with pytest.raises(DatabaseDriverError) as exc_info:
            _ = settings.sync_connection_url

        message = str(exc_info.value)
        assert "psycopg2" in message
        assert "не объявлен" in message
        assert "db_drivers" in message
        assert not isinstance(exc_info.value, ModuleNotFoundError)

    def test_pyodbc_accepted_after_declaration(self) -> None:
        """MSSQL sync (``pyodbc``) объявлен в extra → DSN собирается.

        Wave 13 Q2 (согласовано с владельцем): ``pyodbc`` перенесён в extra
        ``db_drivers``, поэтому рантайм-guard больше не отвергает его.
        """
        settings = _make_settings(
            type=DatabaseTypeChoices.mssql,
            port=1433,
            async_driver="aioodbc",
            sync_driver="pyodbc",
        )
        assert settings.sync_connection_url.startswith("mssql+pyodbc://")

    def test_ibm_db_sa_rejected(self) -> None:
        """DB2 недостижим → fail-fast с объяснением (ADR-0381).

        Диалект ``sqlalchemy.dialects.db2`` удалён в SQLAlchemy 2.0, а
        ``ibm_db_sa`` не объявлен ни в одном extra. Тип отвергается до
        сборки DSN — понятным сообщением вместо ``NoSuchModuleError``.
        """
        settings = _make_settings(
            type=DatabaseTypeChoices.db2,
            port=50000,
            async_driver="ibm_db_sa",
            sync_driver="ibm_db_sa",
        )
        with pytest.raises(DatabaseDriverError) as exc_info:
            _ = settings.sync_connection_url

        message = str(exc_info.value)
        assert "DB2" in message
        assert "не поддерживается" in message

    def test_async_driver_also_validated(self) -> None:
        """Async-драйвер проверяется так же, как sync."""
        settings = _make_settings(async_driver="psycopg2")
        with pytest.raises(DatabaseDriverError):
            _ = settings.async_connection_url

    def test_unknown_driver_is_not_silently_accepted(self) -> None:
        """Любой незнакомый драйвер отвергается (нет «молчаливого» DSN)."""
        settings = _make_settings(sync_driver="totally_unknown_driver")
        with pytest.raises(DatabaseDriverError):
            _ = settings.sync_connection_url


@pytest.mark.unit
class TestDeclaredDriverAvailability:
    """Объявленный, но не установленный драйвер → fail-fast с extra-подсказкой."""

    def test_declared_but_missing_driver_reports_extra(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Драйвер из extra, которого нет в venv → назван нужный extra."""
        import src.backend.core.config.db_drivers as db_drivers

        monkeypatch.setattr(db_drivers, "is_driver_installed", lambda _driver: False)

        settings = _make_settings(sync_driver="oracledb")
        with pytest.raises(DatabaseDriverError) as exc_info:
            _ = settings.sync_connection_url

        message = str(exc_info.value)
        assert "oracledb" in message
        assert DB_DRIVER_DECLARATIONS["oracledb"].extra in message


@pytest.mark.unit
class TestDeclaredDriversStillWork:
    """Драйверы, объявленные в extras, продолжают собирать DSN."""

    def test_mysql_dsn(self) -> None:
        """MySQL: ``mysql+pymysql://`` / ``mysql+aiomysql://``."""
        settings = _make_settings(
            type=DatabaseTypeChoices.mysql,
            port=3306,
            async_driver="aiomysql",
            sync_driver="pymysql",
        )
        assert settings.sync_connection_url.startswith("mysql+pymysql://")
        assert settings.async_connection_url.startswith("mysql+aiomysql://")

    def test_oracle_dsn(self) -> None:
        """Oracle: ``oracle+oracledb://``."""
        settings = _make_settings(
            type=DatabaseTypeChoices.oracle,
            port=1521,
            async_driver="oracledb",
            sync_driver="oracledb",
        )
        assert settings.sync_connection_url.startswith("oracle+oracledb://")

    def test_sqlite_dsn_unaffected(self) -> None:
        """SQLite: драйвер выбирается внутри конструктора, DSN не меняется."""
        settings = _make_settings(
            type=DatabaseTypeChoices.sqlite,
            path="/tmp/test.db",
            username="",
            password="",
            host="",
            port=0,
            name="",
        )
        assert settings.sync_connection_url.startswith("sqlite+pysqlite:///")
        assert settings.async_connection_url.startswith("sqlite+aiosqlite:///")

    def test_mssql_async_dsn_with_declared_driver(self) -> None:
        """MSSQL async (``aioodbc`` объявлен в ``db_drivers``) — DSN строится."""
        settings = _make_settings(
            type=DatabaseTypeChoices.mssql,
            port=1433,
            async_driver="aioodbc",
            sync_driver="pyodbc",
        )
        assert settings.async_connection_url.startswith("mssql+aioodbc://")


@pytest.mark.unit
class TestDeclarationRegistry:
    """Реестр объявлений драйверов — источник истины для рантайм-guard."""

    def test_psycopg_is_declared(self) -> None:
        """``psycopg`` объявлен (extra ``sources-cdc``)."""
        assert DB_DRIVER_DECLARATIONS["psycopg"].extra == "sources-cdc"

    def test_pymysql_is_provided_by_db_drivers_extra(self) -> None:
        """``pymysql`` приходит транзитивно с ``aiomysql`` (extra db_drivers)."""
        declaration = DB_DRIVER_DECLARATIONS["pymysql"]
        assert declaration.extra == "db_drivers"
        assert declaration.distribution == "aiomysql"

    def test_psycopg2_is_not_in_registry(self) -> None:
        """``psycopg2`` отсутствует в реестре объявленных драйверов."""
        assert "psycopg2" not in DB_DRIVER_DECLARATIONS

    def test_psycopg_extra_is_installed_in_compose_image(self) -> None:
        """Образ compose ставит extra, в котором живёт ``psycopg`` (ADR-0381).

        ``psycopg`` объявлен в extra ``sources-cdc``; Dockerfile ставил только
        ``dev-light`` → в контейнере не было драйвера по умолчанию для
        PostgreSQL.
        """
        dockerfile = (_REPO_ROOT / "ops" / "compose" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        extra = DB_DRIVER_DECLARATIONS["psycopg"].extra
        assert f"--extra {extra}" in dockerfile, (
            f"Dockerfile должен ставить extra '{extra}' (psycopg)"
        )
