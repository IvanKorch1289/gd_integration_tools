from typing import ClassVar, Literal, Optional

from pydantic import Field, computed_field, model_validator
from pydantic_settings import SettingsConfigDict

from app.config.config_loader import BaseSettingsWithLoader


__all__ = (
    "DatabaseConnectionSettings",
    "db_connection_settings",
    "MongoConnectionSettings",
    "mongo_connection_settings",
)


class DatabaseConnectionSettings(BaseSettingsWithLoader):
    """Настройки подключения к реляционным базам данных.

    Содержит параметры для подключения и управления пулом соединений.
    Поддерживаемые СУБД: PostgreSQL, Oracle (частично).

    Исключения:
        NotImplementedError: Для неподдерживаемых СУБД
        ValueError: При несовместимых параметрах подключения
    """

    yaml_group: ClassVar[str] = "database"
    model_config = SettingsConfigDict(
        env_prefix="DB_",
        extra="forbid",
    )

    # Основные параметры подключения
    type: Literal["postgresql", "oracle"] = Field(
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
        description="Наименование базы данных",
        examples=["myapp_prod", "ORCL"],
    )

    async_driver: str = Field(
        ...,
        description="Пакет, используемый для асинхронного подключения",
        examples=["asyncpg", "aioodbc"],
    )
    sync_driver: str = Field(
        ...,
        description="Пакет, используемый для синхронного подключения",
        examples=["psycopg2", "cx_oracle"],
    )

    echo: bool = Field(
        ..., description="Включить логирование SQL-запросов", examples=[False]
    )

    # Учетные данные
    username: str = Field(
        ...,
        title="Пользователь",
        min_length=3,
        description="Имя пользователя для аутентификации",
        examples=["app_user"],
    )

    password: str = Field(
        ...,
        title="Пароль",
        min_length=8,
        description="Пароль пользователя базы данных",
        examples=["Str0ngPa$$w0rd"],
    )

    # Настройки пула соединений
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
        ...,
        description="Интервал обновления подключения",
        examples=[3600],
    )

    pool_timeout: int = Field(
        ...,
        description="Таймаут ожидания пула подключений",
        examples=[30],
    )

    # Таймауты и безопасность
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

    ssl_mode: Optional[str] = Field(
        ...,
        title="Режим SSL",
        description="Настройки шифрования соединения (только для PostgreSQL)",
        examples=["require"],
    )

    ca_bundle: Optional[str] = Field(
        ...,
        description="Путь к сертификату",
        examples=["/path/to/ca.crt"],
    )

    max_retries: int = Field(
        ...,
        ge=0,
        description="Максимальное число повторных попыток",
        examples=3,
    )

    circuit_breaker_max_failures: int = Field(
        ...,
        ge=0,
        description="Максимальное количество неуспешных попыток выполнения",
        examples=5,
    )

    circuit_breaker_reset_timeout: int = Field(
        ...,
        ge=0,
        description="Таймаут сброса неуудачных попыток",
        examples=60,
    )

    slow_query_threshold: float = Field(
        ...,
        ge=0,
        description="Длительность (в секундах) для определения медленного запроса",
        examples=[0.5],
    )

    # Вычисляемые свойства
    @computed_field(description="URL асинхронного подключения")
    def async_connection_url(self) -> str:
        """Формирует DSN для асинхронного драйвера."""
        return self._build_dsn(is_async=True)

    @computed_field(description="URL синхронного подключения")
    def sync_connection_url(self) -> str:
        """Формирует DSN для синхронного драйвера."""
        return self._build_dsn(is_async=False)

    def _build_dsn(self, is_async: bool) -> str:
        """Внутренний метод генерации строки подключения."""
        driver = self.async_driver if is_async else self.sync_driver

        if self.type == "postgresql":
            return (
                f"postgresql+{driver}://{self.username}:{self.password}"
                f"@{self.host}:{self.port}/{self.name}"
            )
        raise NotImplementedError("Поддержка Oracle в разработке")

    @model_validator(mode="after")
    def validate_ssl(self) -> "DatabaseConnectionSettings":
        """Проверяет корректность SSL-настроек."""
        if self.ssl_mode and self.type != "postgresql":
            raise ValueError("SSL доступен только для PostgreSQL")
        return self


class MongoConnectionSettings(BaseSettingsWithLoader):
    """Настройки подключения к MongoDB.

    Содержит параметры для работы с MongoDB, включая настройки пула соединений.
    """

    yaml_group: ClassVar[str] = "mongo"
    model_config = SettingsConfigDict(
        env_prefix="MONGO_",
        extra="forbid",
    )

    # Параметры аутентификации
    username: str = Field(
        ...,
        title="Пользователь",
        description="Имя пользователя с правами на базу",
        examples=["mongo_admin"],
    )

    password: str = Field(
        ...,
        title="Пароль",
        min_length=8,
        description="Пароль для аутентификации в MongoDB",
        examples=["M0ng0Pa$$w0rd"],
    )

    name: str = Field(
        ...,
        title="База данных",
        description="Наименование базы данных, к которой будет осуществляться подключение",
        examples=["myapp_prod", "mydb"],
    )

    # Сетевые настройки
    host: str = Field(
        ...,
        title="Хост",
        description="Сервер MongoDB",
        examples=["mongo.example.com"],
    )

    port: int = Field(
        ...,
        title="Порт",
        ge=1,
        le=65535,
        description="Порт для подключения к MongoDB",
        examples=[27017],
    )

    # Управление соединениями
    min_pool_size: int = Field(
        ...,
        title="Мин. размер пула",
        ge=1,
        le=500,
        description="Минимальное количество соединений в пуле",
        examples=[50],
    )

    max_pool_size: int = Field(
        ...,
        title="Макс. размер пула",
        ge=1,
        le=500,
        description="Максимальное количество соединений в пуле",
        examples=[100],
    )

    timeout: int = Field(
        ...,
        title="Таймаут",
        description="Время ожидания подключения (миллисекунды)",
        examples=[5000],
    )

    @computed_field(description="Строка подключения MongoDB")
    def connection_string(self) -> str:
        """Формирует полную строку подключения с аутентификацией."""
        return (
            f"mongodb://{self.username}:{self.password}@"
            f"{self.host}:{self.port}/{self.name}?authSource=admin"
        )


# Предварительно инициализированные конфигурации
db_connection_settings = DatabaseConnectionSettings()
"""Глобальные настройки реляционных БД"""

mongo_connection_settings = MongoConnectionSettings()
"""Глобальные настройки MongoDB"""
