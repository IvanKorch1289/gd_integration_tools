from enum import Enum

__all__ = ("DatabaseProfileChoices", "DatabaseTypeChoices", "IsolationLevelChoices")


class DatabaseTypeChoices(str, Enum):
    """
    Перечисление поддерживаемых реляционных СУБД.

    Значения:
        postgresql (str): PostgreSQL.
        oracle (str): Oracle.
        sqlite (str): SQLite (профиль dev_light, W21.2).
        mssql (str): Microsoft SQL Server (S104 W3).
        mysql (str): MySQL / MariaDB (S104 W3).
        db2 (str): IBM Db2 (S104 W3).
    """

    postgresql = "postgresql"
    oracle = "oracle"
    sqlite = "sqlite"
    mssql = "mssql"  # S104 W3
    mysql = "mysql"  # S104 W3
    db2 = "db2"  # S104 W3


class IsolationLevelChoices(str, Enum):
    """
    Перечисление допустимых уровней изоляции транзакций.

    Значения:
        read_committed (str): Уровень READ COMMITTED.
        repeatable_read (str): Уровень REPEATABLE READ.
        serializable (str): Уровень SERIALIZABLE.
    """

    read_committed = "READ COMMITTED"
    repeatable_read = "REPEATABLE READ"
    serializable = "SERIALIZABLE"


class DatabaseProfileChoices(str, Enum):
    """
    Перечисление профилей подключения к БД.

    Значения:
        main (str): Основная БД проекта.
        oracle (str): Внешняя Oracle БД.
        postgres (str): Внешняя PostgreSQL БД.
    """

    main = "main"
    oracle = "oracle"
    postgres = "postgres"
