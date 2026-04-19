from urllib.parse import quote_plus

from pydantic import Field, SecretStr, computed_field

from app.core.config.external_databases.item_settings import ExternalDatabaseItemSettings
from app.core.enums.database import DatabaseTypeChoices

__all__ = ("ExternalDatabaseConnectionSettings",)


class ExternalDatabaseConnectionSettings(ExternalDatabaseItemSettings):
    """
    Итоговые настройки подключения к внешней реляционной БД.

    Это уже "разрешённая" модель:
    - общие настройки подмешаны;
    - profile-specific overrides применены;
    - username/password получены из env/Vault.
    """

    echo: bool = Field(
        ..., description="Включить логирование SQL-запросов", examples=[False]
    )

    username: str = Field(
        ...,
        title="Пользователь",
        min_length=1,
        description="Имя пользователя для аутентификации",
        exclude=True,
        repr=False,
        examples=["ext_user"],
    )

    password: SecretStr = Field(
        ...,
        title="Пароль",
        description="Пароль пользователя внешней БД",
        exclude=True,
        repr=False,
    )

    pool_size: int = Field(
        ...,
        title="Размер пула",
        ge=1,
        description="Максимальное количество активных соединений",
        examples=[5],
    )

    max_overflow: int = Field(
        ...,
        title="Доп. соединения",
        ge=0,
        description="Максимум временных соединений поверх пула",
        examples=[5],
    )

    pool_recycle: int = Field(
        ..., description="Интервал обновления подключения", examples=[1800]
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
        ..., ge=0, description="Максимальное число повторных попыток", examples=[0]
    )

    circuit_breaker_max_failures: int = Field(
        ...,
        ge=0,
        description="Максимальное количество неуспешных попыток выполнения",
        examples=[5],
    )

    circuit_breaker_reset_timeout: int = Field(
        ..., ge=0, description="Таймаут сброса неудачных попыток", examples=[30]
    )

    slow_query_threshold: float = Field(
        ...,
        ge=0,
        description="Длительность (в секундах) для определения медленного запроса",
        examples=[1.0],
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
        """
        driver = self.async_driver if is_async else self.sync_driver
        username = quote_plus(self.username)
        password = quote_plus(self.password.get_secret_value())

        if self.type == DatabaseTypeChoices.postgresql:
            return (
                f"postgresql+{driver}://{username}:{password}"
                f"@{self.host}:{self.port}/{self.db_name}"
            )

        if self.type == DatabaseTypeChoices.oracle:
            if self.service_name:
                return (
                    f"oracle+{driver}://{username}:{password}"
                    f"@{self.host}:{self.port}/?service_name={self.service_name}"
                )

            return (
                f"oracle+{driver}://{username}:{password}"
                f"@{self.host}:{self.port}/?sid={self.sid}"
            )

        raise NotImplementedError(f"Поддержка СУБД '{self.type}' не реализована")
