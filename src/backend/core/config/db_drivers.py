"""Реестр DSN-драйверов и fail-fast проверка их наличия (Wave 13 Q9).

Проблема: DSN-конструкторы (``core/config/database.py``,
``core/config/external_databases/connection.py``) обещали драйверы, которых
нет в окружении — ``psycopg2`` (не объявлен ни в одном extra, отсутствует в
lock-файле), ``pyodbc``/``ibm_db_sa``/``cx_Oracle`` (не объявлены). Ошибка
возникала в рантайме внутри SQLAlchemy как невнятный ``ModuleNotFoundError``
без подсказки, что именно доустановить.

Контракт:

* :data:`DB_DRIVER_DECLARATIONS` — источник истины «как проект объявляет
  драйвер» (extra + дистрибутив-поставщик). Используется и рантайм-guard'ом,
  и статическим гейтом ``tools/check_dsn_drivers.py``;
* :func:`ensure_driver_available` — fail-fast перед сборкой DSN: драйвер
  либо объявлен в проекте, либо — явная ошибка с понятным сообщением.

Модуль намеренно зависит только от stdlib: его импортирует CI-гейт
(``tools/``) без поднятия конфигурации приложения.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Final

__all__ = (
    "DB_DRIVER_DECLARATIONS",
    "DatabaseDriverError",
    "DriverDeclaration",
    "ensure_driver_available",
    "is_driver_installed",
)


@dataclass(frozen=True, slots=True)
class DriverDeclaration:
    """Как проект объявляет DSN-драйвер в манифесте зависимостей.

    Attrs:
        extra: Имя extra из ``[project.optional-dependencies]`` в
            ``pyproject.toml`` (``core`` — базовая зависимость, ``stdlib`` —
            модуль стандартной библиотеки).
        distribution: Имя дистрибутива, который фактически ставит драйвер.
            Для транзитивных случаев (например ``pymysql`` приезжает с
            ``aiomysql``) указан поставщик — ``aiomysql``.
    """

    extra: str
    distribution: str


DB_DRIVER_DECLARATIONS: Final[dict[str, DriverDeclaration]] = {
    # PostgreSQL
    "asyncpg": DriverDeclaration(extra="core", distribution="asyncpg"),
    "psycopg": DriverDeclaration(extra="sources-cdc", distribution="psycopg"),
    # SQLite
    "aiosqlite": DriverDeclaration(extra="dev-light", distribution="aiosqlite"),
    "pysqlite": DriverDeclaration(extra="stdlib", distribution="sqlite3"),
    "sqlite3": DriverDeclaration(extra="stdlib", distribution="sqlite3"),
    # Oracle
    "oracledb": DriverDeclaration(extra="db_drivers", distribution="oracledb"),
    # MSSQL
    "aioodbc": DriverDeclaration(extra="db_drivers", distribution="aioodbc"),
    "pyodbc": DriverDeclaration(extra="db_drivers", distribution="pyodbc"),
    # ClickHouse (аналитика)
    "clickhouse_connect": DriverDeclaration(
        extra="db_drivers", distribution="clickhouse-connect"
    ),
    # MySQL
    "aiomysql": DriverDeclaration(extra="db_drivers", distribution="aiomysql"),
    # PyMySQL приезжает транзитивной зависимостью aiomysql (extra db_drivers)
    "pymysql": DriverDeclaration(extra="db_drivers", distribution="aiomysql"),
}
"""Драйверы, объявленные проектом: driver module → как он предоставляется."""


class DatabaseDriverError(ValueError):
    """DSN-драйвер не объявлен в проекте либо не установлен в окружении.

    Заменяет поздний ``ModuleNotFoundError`` из SQLAlchemy: сообщение
    называет драйвер, extra, который его ставит, и конкретное действие.
    """


def is_driver_installed(driver: str) -> bool:
    """Проверяет, присутствует ли модуль драйвера в текущем окружении.

    Используется ``find_spec`` (без импорта): импорт драйвера тянет
    нативные библиотеки (ODBC, libpq) и может падать уже на этапе
    импорта — для проверки наличия достаточно спецификации модуля.
    """
    try:
        return importlib.util.find_spec(driver) is not None
    except ImportError:
        return False
    except ValueError:
        return False


def ensure_driver_available(driver: str) -> None:
    """Fail-fast проверка DSN-драйвера перед сборкой строки подключения.

    Args:
        driver: Имя модуля драйвера (``psycopg``, ``asyncpg``, ...).

    Raises:
        DatabaseDriverError: драйвер не объявлен ни в одном extra проекта
            либо объявлен, но отсутствует в текущем окружении.
    """
    declaration = DB_DRIVER_DECLARATIONS.get(driver)
    if declaration is None:
        known = ", ".join(sorted(DB_DRIVER_DECLARATIONS))
        raise DatabaseDriverError(
            f"Драйвер '{driver}' не объявлен ни в одном extra проекта "
            f"([project.optional-dependencies] в pyproject.toml). "
            f"Добавьте его в extra 'db_drivers' либо используйте один из "
            f"объявленных драйверов: {known}."
        )

    if declaration.extra == "stdlib":
        return

    if not is_driver_installed(driver):
        raise DatabaseDriverError(
            f"Драйвер '{driver}' объявлен в extra '{declaration.extra}', "
            f"но не установлен в текущем окружении. "
            f"Установите: pip install 'gd-advanced-tools[{declaration.extra}]'."
        )
