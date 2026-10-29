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
  либо объявлен в проекте, либо — явная ошибка с понятным сообщением;
* :data:`DB_TYPE_DRIVER_PAIRS` — матрица допустимых драйверов по паре
  (тип СУБД, sync/async). Без неё MSSQL/MySQL наследовали PG-драйверы
  (``asyncpg``) → DSN ``mssql+asyncpg://`` → ``NoSuchModuleError`` уже в
  рантайме (ADR-0381);
* :func:`ensure_driver_pair_supported` — fail-fast на несовместимой паре
  (тип СУБД, драйвер);
* :func:`ensure_db_type_supported` — fail-fast на типах, недостижимых через
  SQLAlchemy DSN (DB2, ClickHouse).

Модуль намеренно зависит только от stdlib: его импортирует CI-гейт
(``tools/``) без поднятия конфигурации приложения.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Final

__all__ = (
    "DB_DRIVER_DECLARATIONS",
    "DB_TYPE_DRIVER_PAIRS",
    "UNSUPPORTED_SQLALCHEMY_DB_TYPES",
    "DatabaseDriverError",
    "DriverDeclaration",
    "ensure_db_type_supported",
    "ensure_driver_available",
    "ensure_driver_pair_supported",
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


DB_TYPE_DRIVER_PAIRS: Final[dict[str, dict[str, frozenset[str]]]] = {
    "postgresql": {
        "async": frozenset({"asyncpg", "psycopg"}),
        "sync": frozenset({"psycopg"}),
    },
    "oracle": {"async": frozenset({"oracledb"}), "sync": frozenset({"oracledb"})},
    "mssql": {"async": frozenset({"aioodbc"}), "sync": frozenset({"pyodbc"})},
    "mysql": {"async": frozenset({"aiomysql"}), "sync": frozenset({"pymysql"})},
}
"""Допустимые драйверы по паре (тип СУБД, режим подключения).

Ключ верхнего уровня — значение ``DatabaseTypeChoices`` (строка), второй
уровень — ``async``/``sync``. Матрица закрывает дефект ADR-0381: без неё
дефолтные PG-драйверы (``asyncpg``/``psycopg``) применялись к MSSQL/MySQL
и давали невалидный DSN (``mssql+asyncpg://`` → ``NoSuchModuleError``).
"""


UNSUPPORTED_SQLALCHEMY_DB_TYPES: Final[dict[str, str]] = {
    "db2": (
        "DB2 не поддерживается: диалект sqlalchemy.dialects.db2 удалён в "
        "SQLAlchemy 2.0, а драйвер ibm_db_sa не объявлен ни в одном extra "
        "проекта. Подключайтесь к DB2 напрямую через ibm_db, вне DSN-контура."
    ),
    "clickhouse": (
        "ClickHouse не поддерживается через SQLAlchemy DSN: диалект clickhouse "
        "в SQLAlchemy отсутствует, а DSN 'clickhouse://' невалиден для "
        "SQLAlchemy. Используйте отдельный клиент "
        "src/backend/infrastructure/clients/storage/clickhouse.py "
        "(настройки — core/config/clickhouse.py)."
    ),
}
"""Типы СУБД, недостижимые через SQLAlchemy DSN (ADR-0381)."""


class DatabaseDriverError(ValueError):
    """DSN-драйвер несовместим, не объявлен в проекте либо не установлен.

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


def ensure_db_type_supported(db_type: str) -> None:
    """Fail-fast: тип СУБД достижим через SQLAlchemy DSN.

    Args:
        db_type: Тип СУБД (значение ``DatabaseTypeChoices``).

    Raises:
        DatabaseDriverError: тип СУБД не имеет SQLAlchemy-диалекта в проекте
            (DB2 — диалект удалён в SQLAlchemy 2.0; ClickHouse — отдельный
            клиент) либо тип неизвестен DSN-контуру.
    """
    unsupported = UNSUPPORTED_SQLALCHEMY_DB_TYPES.get(db_type)
    if unsupported is not None:
        raise DatabaseDriverError(unsupported)

    if db_type not in DB_TYPE_DRIVER_PAIRS:
        raise DatabaseDriverError(
            f"Тип СУБД '{db_type}' не поддерживается DSN-контуром "
            f"(поддерживаются: {', '.join(sorted(DB_TYPE_DRIVER_PAIRS))})."
        )


def ensure_driver_pair_supported(db_type: str, *, is_async: bool, driver: str) -> None:
    """Fail-fast: драйвер совместим с типом СУБД и режимом подключения.

    Вызывается **после** :func:`ensure_driver_available`: для необъявленного
    драйвера важнее сообщение «не объявлен в extra», чем «несовместим»;
    несовместимость проверяется для драйверов, которые в проекте есть.

    Args:
        db_type: Тип СУБД (значение ``DatabaseTypeChoices``).
        is_async: ``True`` — async-подключение, ``False`` — sync.
        driver: Имя модуля драйвера (``asyncpg``, ``psycopg``, ...).

    Raises:
        DatabaseDriverError: тип СУБД недостижим через SQLAlchemy DSN
            (DB2, ClickHouse) либо драйвер несовместим с типом/режимом.
    """
    ensure_db_type_supported(db_type)

    mode = "async" if is_async else "sync"
    permitted = DB_TYPE_DRIVER_PAIRS[db_type][mode]
    if driver not in permitted:
        raise DatabaseDriverError(
            f"Драйвер '{driver}' несовместим с типом СУБД '{db_type}' "
            f"({mode}-подключение): DSN '{db_type}+{driver}://' невалиден. "
            f"Допустимые драйверы: {', '.join(sorted(permitted))}. "
            "Проверьте database.async_driver / database.sync_driver в профиле."
        )
