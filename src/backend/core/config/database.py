from typing import ClassVar

from pydantic import Field, computed_field, model_validator
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader
from src.core.enums.database import DatabaseTypeChoices

__all__ = ("DatabaseConnectionSettings", "db_connection_settings")


class DatabaseConnectionSettings(BaseSettingsWithLoader):
    """
    Настройки подключения к реляционным базам данных.

    Содержит параметры для подключения и управления пулом соединений.
    Поддерживаемые СУБД: PostgreSQL, Oracle.
    """

    yaml_group: ClassVar[str] = "database"
    model_config = SettingsConfigDict(env_prefix="DB_", extra="forbid")

    type: DatabaseTypeChoices = Field(
        ...,
        title="Тип СУБД",
        description="Тип системы управления базами данных",
        examples=["postgresql"],
    )

    host: str = Field(
        default="",
        title="Хост",
        max_length=253,
        description="Сервер базы данных (IP или доменное имя). Игнорируется для sqlite.",
        examples=["db.example.com"],
    )

    port: int = Field(
        default=0,
        title="Порт",
        ge=0,
        lt=65536,
        description="Порт для подключения к СУБД. Игнорируется для sqlite.",
        examples=[5432],
    )

    name: str = Field(
        default="",
        description="Наименование базы данных или service_name",
        examples=["myapp_prod", "ORCL"],
    )

    path: str | None = Field(
        default=None,
        description=(
            "Путь к файлу SQLite (для type=sqlite). "
            "Поддерживаются относительные пути и ':memory:'."
        ),
        examples=["./.run/dev.sqlite3", ":memory:"],
    )

    async_driver: str = Field(
        default="asyncpg",
        description=(
            "Пакет асинхронного драйвера. Для sqlite по умолчанию используется "
            "'aiosqlite' (если значение оставлено для PG)."
        ),
        examples=["asyncpg", "oracledb_async", "aiosqlite"],
    )

    sync_driver: str = Field(
        default="psycopg2",
        description=(
            "Пакет синхронного драйвера. Для sqlite используется встроенный 'pysqlite'."
        ),
        examples=["psycopg2", "oracledb", "pysqlite"],
    )

    echo: bool = Field(
        default=False, description="Включить логирование SQL-запросов", examples=[False]
    )

    username: str = Field(
        default="",
        title="Пользователь",
        description="Имя пользователя для аутентификации. Игнорируется для sqlite.",
        examples=["app_user"],
    )

    password: str = Field(
        default="",
        title="Пароль",
        description="Пароль пользователя базы данных. Игнорируется для sqlite.",
        examples=["Str0ngPa$$w0rd"],
    )

    pool_size: int = Field(
        ...,
        title="Размер пула",
        ge=1,
        description="Максимальное количество активных соединений",
        examples=[20],
    )

    max_overflow: int = Field(
        ...,
        title="Доп. соединения",
        ge=0,
        description="Максимум временных соединений поверх пула",
        examples=[10],
    )

    pool_recycle: int = Field(
        ..., description="Интервал обновления подключения", examples=[3600]
    )

    pool_timeout: int = Field(
        ..., description="Таймаут ожидания пула подключений", examples=[30]
    )

    connect_timeout: int = Field(
        ...,
        title="Таймаут подключения",
        ge=1,
        description="Максимальное время установки соединения (секунды)",
        examples=[10],
    )

    command_timeout: int = Field(
        ...,
        description="Максимальное время выполнения запроса (секунды)",
        examples=[30],
    )

    ssl_mode: str | None = Field(
        default=None,
        title="Режим SSL",
        description="Настройки шифрования соединения (только для PostgreSQL)",
        examples=["require"],
    )

    ca_bundle: str | None = Field(
        default=None, description="Путь к сертификату", examples=["/path/to/ca.crt"]
    )

    max_retries: int = Field(
        ..., ge=0, description="Максимальное число повторных попыток", examples=[3]
    )

    circuit_breaker_max_failures: int = Field(
        ...,
        ge=0,
        description="Максимальное количество неуспешных попыток выполнения",
        examples=[5],
    )

    circuit_breaker_reset_timeout: int = Field(
        ..., ge=0, description="Таймаут сброса неудачных попыток", examples=[60]
    )

    slow_query_threshold: float = Field(
        ...,
        ge=0,
        description="Длительность (в секундах) для определения медленного запроса",
        examples=[0.5],
    )

    @computed_field(description="URL асинхронного подключения")
    def async_connection_url(self) -> str:
        """Формирует DSN для асинхронного драйвера."""
        return self._build_dsn(is_async=True)

    @computed_field(description="URL синхронного подключения")
    def sync_connection_url(self) -> str:
        """Формирует DSN для синхронного драйвера."""
        return self._build_dsn(is_async=False)

    def _build_dsn(self, is_async: bool) -> str:
        """
        Внутренний метод генерации строки подключения.

        Примечание:
            Для Oracle поле `name` трактуется как `service_name`.
            Для SQLite используется ``path`` (для ``:memory:`` префикс пустой).
        """
        if self.type == DatabaseTypeChoices.sqlite:
            driver = "aiosqlite" if is_async else "pysqlite"
            target = self.path or ":memory:"
            return f"sqlite+{driver}:///{target}"

        driver = self.async_driver if is_async else self.sync_driver

        if self.type == DatabaseTypeChoices.postgresql:
            return (
                f"postgresql+{driver}://{self.username}:{self.password}"
                f"@{self.host}:{self.port}/{self.name}"
            )

        if self.type == DatabaseTypeChoices.oracle:
            return (
                f"oracle+{driver}://{self.username}:{self.password}"
                f"@{self.host}:{self.port}/?service_name={self.name}"
            )

        raise NotImplementedError(f"Поддержка СУБД '{self.type}' не реализована")

    @model_validator(mode="after")
    def validate_ssl(self) -> "DatabaseConnectionSettings":
        """Проверяет корректность SSL-настроек."""
        if self.ssl_mode and self.type != DatabaseTypeChoices.postgresql:
            raise ValueError("SSL доступен только для PostgreSQL")
        return self

    @model_validator(mode="after")
    def validate_oracle_drivers(self) -> "DatabaseConnectionSettings":
        """Для Oracle драйверы PG-семейства не работают.

        В ``base.yml`` зашиты PG-defaults ``asyncpg``/``psycopg2``. При
        переключении профиля на Oracle их обязательно переопределить в
        overlay (``async_driver=oracledb``, ``sync_driver=oracledb``);
        иначе DSN строится с неверным префиксом и падает в рантайме.
        """
        if self.type == DatabaseTypeChoices.oracle:
            invalid = {"asyncpg", "psycopg2", "psycopg"}
            if self.async_driver in invalid or self.sync_driver in invalid:
                raise ValueError(
                    "Для type=oracle требуются драйверы oracledb-семейства; "
                    f"получено async_driver={self.async_driver!r}, "
                    f"sync_driver={self.sync_driver!r}. Переопределите в "
                    "config_profiles/{profile}.yml::database: "
                    "async_driver=oracledb, sync_driver=oracledb."
                )
        return self

    @model_validator(mode="after")
    def validate_required_fields(self) -> "DatabaseConnectionSettings":
        """Проверяет наличие обязательных полей в зависимости от типа СУБД."""
        if self.type == DatabaseTypeChoices.sqlite:
            if not self.path:
                raise ValueError("Для type=sqlite обязательно поле 'path'.")
            return self

        # postgresql / oracle: требуем сетевые параметры
        if not self.host or len(self.host) < 3:
            raise ValueError(
                f"Для type={self.type.value} требуется host (min 3 символа)."
            )
        if self.port <= 0:
            raise ValueError(f"Для type={self.type.value} требуется валидный port.")
        if not self.username:
            raise ValueError(f"Для type={self.type.value} требуется username.")
        if not self.password:
            raise ValueError(f"Для type={self.type.value} требуется password.")
        return self


db_connection_settings = DatabaseConnectionSettings()
"""Глобальные настройки реляционных БД"""
