from urllib.parse import quote_plus

from pydantic import Field, SecretStr, computed_field, field_serializer

from src.backend.core.config.base import mask_url_password
from src.backend.core.config.db_drivers import (
    DatabaseDriverError,
    ensure_driver_available,
)
from src.backend.core.config.external_databases.item import ExternalDatabaseItemSettings
from src.backend.core.enums.database import DatabaseTypeChoices
from src.backend.core.logging import get_logger

__all__ = ("ExternalDatabaseConnectionSettings",)

_logger = get_logger("config.external_databases")


class ExternalDatabaseConnectionSettings(ExternalDatabaseItemSettings):
    """Итоговые настройки подключения к внешней реляционной БД.

    Это уже "разрешённая" модель:
    - общие настройки подмешаны;
    - profile-specific overrides применены;
    - username/password получены из env/Vault.
    """

    echo: bool = Field(
        ..., description="Включить логирование SQL-запросов", examples=[False]
    )

    username: str | None = Field(
        default=None,
        title="Пользователь",
        min_length=1,
        description="Имя пользователя для аутентификации",
        exclude=True,
        repr=False,
        examples=["ext_user"],
    )

    password: SecretStr | None = Field(
        default=None,
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

    pool_pre_ping: bool = Field(
        default=True,
        title="Pool pre-ping",
        description=(
            "Sprint 6 K2: SQLAlchemy ``pool_pre_ping`` для resolved-config "
            "external connection. Перед выдачей connection из pool выполняется "
            "SELECT 1 для отсева умерших соединений (V15 R-V15-14)."
        ),
        examples=[True],
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

    replica_dsn: str | None = Field(
        default=None,
        description="DSN read-replica для async-подключения (S38.1).",
        examples=["postgresql+asyncpg://user:pwd@replica:5432/test"],
    )

    pool_use_lifo: bool = Field(
        default=False,
        description="SQLAlchemy pool_use_lifo: True — LIFO, False — FIFO (default).",
        examples=[False],
    )

    @computed_field(repr=False, description="URL асинхронного подключения")
    def async_connection_url(self) -> str:
        """Формирует DSN для асинхронного драйвера."""
        return self._build_dsn(is_async=True)

    @computed_field(repr=False, description="URL асинхронного подключения к read-replica")
    def replica_async_connection_url(self) -> str | None:
        """Возвращает DSN read-replica если задана."""
        return self.replica_dsn

    @computed_field(repr=False, description="URL синхронного подключения")
    def sync_connection_url(self) -> str:
        """Формирует DSN для синхронного драйвера."""
        return self._build_dsn(is_async=False)

    @field_serializer("async_connection_url", "sync_connection_url")
    def _serialize_connection_urls(self, value: str) -> str:
        """Маскирует пароль в дампе модели (ADR-0378, ADR-0385 A7).

        ``repr=False`` скрывает DSN только из ``__repr__`` — в
        ``model_dump()``/``model_dump_json()`` пароль утекал открытым
        текстом (и ``GET /api/v1/admin/config`` отдавал его клиенту).
        Атрибуты DSN остаются рабочими: SQLAlchemy подключается с
        настоящим паролем.
        """
        return mask_url_password(value)

    def _build_dsn(self, is_async: bool) -> str:
        """Внутренний метод генерации строки подключения.

        Wave 13 Q9: драйвер проверяется на объявленность/наличие до сборки
        DSN — иначе необъявленный драйвер падал бы в рантайме как
        ``ModuleNotFoundError`` внутри SQLAlchemy.

        ADR-0385 (A8): computed-поля НЕ ДОЛЖНЫ ронять ``model_dump()``
        (admin-эндпоинт отдавал 500). Поэтому:
        * отсутствие драйвера логируется предупреждением, DSN собирается
          как есть (ошибка подключения проявится при создании engine'а);
        * отсутствие кредов не приводит к исключению — DSN собирается
          без userinfo-части.
        """
        driver = self.async_driver if is_async else self.sync_driver
        try:
            ensure_driver_available(driver)
        except DatabaseDriverError as driver_exc:
            _logger.warning(
                "Драйвер внешней БД недоступен — DSN собран без fail-fast: %s",
                driver_exc,
            )
        username = quote_plus(self.username) if self.username else ""
        password = (
            quote_plus(self.password.get_secret_value()) if self.password else ""
        )
        userinfo = f"{username}:{password}@" if username or password else ""

        if self.type == DatabaseTypeChoices.postgresql:
            return (
                f"postgresql+{driver}://{userinfo}"
                f"{self.host}:{self.port}/{self.db_name}"
            )

        if self.type == DatabaseTypeChoices.oracle:
            if self.service_name:
                return (
                    f"oracle+{driver}://{userinfo}"
                    f"{self.host}:{self.port}/?service_name={self.service_name}"
                )

            return (
                f"oracle+{driver}://{userinfo}"
                f"{self.host}:{self.port}/?sid={self.sid}"
            )

        raise NotImplementedError(f"Поддержка СУБД '{self.type}' не реализована")
