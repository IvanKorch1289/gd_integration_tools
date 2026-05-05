from enum import Enum

__all__ = ("DatabaseTypeChoices", "IsolationLevelChoices", "DatabaseProfileChoices")


class DatabaseTypeChoices(str, Enum):
    """
    Перечисление поддерживаемых реляционных СУБД.

    Значения:
        postgresql (str): PostgreSQL.
        oracle (str): Oracle.
        sqlite (str): SQLite (профиль dev_light, W21.2).
    """

    postgresql = "postgresql"
    oracle = "oracle"
    sqlite = "sqlite"


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
