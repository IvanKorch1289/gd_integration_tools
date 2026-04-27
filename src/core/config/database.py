from typing import ClassVar

from pydantic import Field, computed_field, model_validator
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader
from src.core.enums.database import DatabaseTypeChoices

__all__ = (
    "DatabaseConnectionSettings",
    "db_connection_settings",
)


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
        ...,
        title="Хост",
        min_length=3,
        max_length=253,
        description="Сервер базы данных (IP или доменное имя)",
        examples=["db.example.com"],
    )

    port: int = Field(
        ...,
        title="Порт",
        gt=0,
        lt=65536,
        description="Порт для подключения к СУБД",
        examples=[5432],
    )

    name: str = Field(
        ...,
        description="Наименование базы данных или service_name",
        examples=["myapp_prod", "ORCL"],
    )

    async_driver: str = Field(
        ...,
        description="Пакет, используемый для асинхронного подключения",
        examples=["asyncpg", "oracledb_async"],
    )

    sync_driver: str = Field(
        ...,
        description="Пакет, используемый для синхронного подключения",
        examples=["psycopg2", "oracledb"],
    )

    echo: bool = Field(
        ..., description="Включить логирование SQL-запросов", examples=[False]
    )

    username: str = Field(
        ...,
        title="Пользователь",
        min_length=1,
        description="Имя пользователя для аутентификации",
        examples=["app_user"],
    )

    password: str = Field(
        ...,
        title="Пароль",
        min_length=1,
        description="Пароль пользователя базы данных",
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
        """
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


db_connection_settings = DatabaseConnectionSettings()
"""Глобальные настройки реляционных БД"""
