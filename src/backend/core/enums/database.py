from enum import StrEnum

__all__ = ("DatabaseProfileChoices", "DatabaseTypeChoices", "IsolationLevelChoices")


class DatabaseTypeChoices(StrEnum):
    """Перечисление поддерживаемых реляционных СУБД.

    Значения:
        postgresql (str): PostgreSQL.
        oracle (str): Oracle.
        sqlite (str): SQLite (профиль dev_light, W21.2).
        mssql (str): Microsoft SQL Server (S104 W3).
        mysql (str): MySQL / MariaDB (S104 W3).
        db2 (str): IBM Db2 (S104 W3). **Недостижим через SQLAlchemy DSN**
            (ADR-0381): диалект ``sqlalchemy.dialects.db2`` удалён в
            SQLAlchemy 2.0, драйвер ``ibm_db_sa`` не объявлен — значение
            отвергается fail-fast. Остаётся в enum, т.к. на него ссылается
            внешний контур (``external_databases``).
        clickhouse (str): ClickHouse (S168 W10 P1-8; analytics path,
            ``clickhouse_connect`` driver). **Недостижим через SQLAlchemy
            DSN** (ADR-0381) — отдельный клиент
            ``infrastructure/clients/storage/clickhouse.py``.
    """

    postgresql = "postgresql"
    oracle = "oracle"
    sqlite = "sqlite"
    mssql = "mssql"  # S104 W3
    mysql = "mysql"  # S104 W3
    db2 = "db2"  # S104 W3 (fail-fast: нет SQLAlchemy-диалекта, ADR-0381)
    clickhouse = "clickhouse"  # S168 W10 P1-8 (analytics; ADR-0381)


class IsolationLevelChoices(StrEnum):
    """Перечисление допустимых уровней изоляции транзакций.

    Значения:
        read_committed (str): Уровень READ COMMITTED.
        repeatable_read (str): Уровень REPEATABLE READ.
        serializable (str): Уровень SERIALIZABLE.
    """

    read_committed = "READ COMMITTED"
    repeatable_read = "REPEATABLE READ"
    serializable = "SERIALIZABLE"


class DatabaseProfileChoices(StrEnum):
    """Перечисление профилей подключения к БД.

    Значения:
        main (str): Основная БД проекта.
        oracle (str): Внешняя Oracle БД.
        postgres (str): Внешняя PostgreSQL БД.
    """

    main = "main"
    oracle = "oracle"
    postgres = "postgres"
