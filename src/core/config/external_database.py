from os import getenv
from re import sub
from typing import ClassVar
from urllib.parse import quote_plus

from pydantic import BaseModel, Field, SecretStr, computed_field, model_validator
from pydantic_settings import SettingsConfigDict

from app.core.config.config_loader import BaseSettingsWithLoader
from app.core.enums.database import DatabaseTypeChoices

__all__ = (
    "ExternalDatabaseItemSettings",
    "ExternalDatabaseConnectionSettings",
    "ExternalDatabasesSettings",
    "external_databases_settings",
)


class ExternalDatabaseItemSettings(BaseModel):
    """
    Настройки одного внешнего подключения.

    Используется как элемент списка `connections` внутри группы
    `external_databases` в config.yml.
    """

    name: str = Field(
        ...,
        title="Техническое имя подключения",
        min_length=1,
        max_length=100,
        description="Короткое техническое имя подключения",
        examples=["oracle_1", "pg_1"],
    )

    profile_name: str = Field(
        ...,
        title="Профиль подключения",
        min_length=1,
        max_length=100,
        description="Уникальный профиль подключения для выбора БД в сервисе",
        examples=["oracle_1", "pg_1"],
    )

    type: DatabaseTypeChoices = Field(
        ...,
        title="Тип СУБД",
        description="Тип внешней реляционной базы данных",
        examples=["oracle", "postgresql"],
    )

    host: str = Field(
        ...,
        title="Хост",
        min_length=3,
        max_length=253,
        description="Сервер внешней базы данных (IP или доменное имя)",
        examples=["10.10.10.11", "db.example.com"],
    )

    port: int = Field(
        ...,
        title="Порт",
        gt=0,
        lt=65536,
        description="Порт для подключения к внешней СУБД",
        examples=[1521, 5432],
    )

    sid: str | None = Field(
        default=None,
        title="Oracle SID",
        min_length=1,
        description="SID Oracle, если подключение выполняется по SID",
        examples=["ORCL"],
    )

    service_name: str | None = Field(
        default=None,
        title="Oracle service_name",
        min_length=1,
        description="Service name Oracle, если подключение выполняется по service_name",
        examples=["XEPDB1"],
    )

    db_name: str | None = Field(
        default=None,
        title="Имя базы данных PostgreSQL",
        min_length=1,
        description="Имя базы данных для PostgreSQL-подключения",
        examples=["analytics"],
    )

    async_driver: str = Field(
        ...,
        title="Асинхронный драйвер",
        min_length=1,
        description="Пакет, используемый для асинхронного подключения",
        examples=["asyncpg", "oracledb"],
    )

    sync_driver: str = Field(
        ...,
        title="Синхронный драйвер",
        min_length=1,
        description="Пакет, используемый для синхронного подключения",
        examples=["psycopg2", "oracledb"],
    )

    schema: str = Field(
        ...,
        title="Схема",
        min_length=1,
        description="Базовая схема, в которой находятся view/procedure/function",
        examples=["public", "REPORTING"],
    )

    enabled: bool = Field(
        default=True,
        title="Подключение активно",
        description="Флаг активности внешнего подключения",
        examples=[True],
    )

    echo: bool | None = Field(
        default=None,
        title="Логирование SQL",
        description="Переопределение общего флага логирования SQL-запросов",
        examples=[False],
    )

    pool_size: int | None = Field(
        default=None,
        title="Размер пула",
        ge=1,
        description="Переопределение максимального количества активных соединений",
        examples=[10],
    )

    max_overflow: int | None = Field(
        default=None,
        title="Доп. соединения",
        ge=0,
        description="Переопределение максимума временных соединений поверх пула",
        examples=[5],
    )

    pool_recycle: int | None = Field(
        default=None,
        title="Пересоздание соединения",
        ge=0,
        description="Переопределение интервала обновления подключения",
        examples=[1800],
    )

    pool_timeout: int | None = Field(
        default=None,
        title="Таймаут пула",
        ge=0,
        description="Переопределение таймаута ожидания соединения из пула",
        examples=[30],
    )

    connect_timeout: int | None = Field(
        default=None,
        title="Таймаут подключения",
        ge=1,
        description="Переопределение максимального времени установки соединения",
        examples=[10],
    )

    command_timeout: int | None = Field(
        default=None,
        title="Таймаут команды",
        ge=1,
        description="Переопределение максимального времени выполнения запроса",
        examples=[30],
    )

    ssl_mode: str | None = Field(
        default=None,
        title="Режим SSL",
        description="Переопределение режима SSL для PostgreSQL",
        examples=["prefer", "require"],
    )

    ca_bundle: str | None = Field(
        default=None,
        title="CA bundle",
        description="Путь к корневому сертификату для SSL-подключения",
        examples=["/app/certs/external-pg-ca.crt"],
    )

    max_retries: int | None = Field(
        default=None,
        title="Максимум retry",
        ge=0,
        description="Переопределение числа повторных попыток",
        examples=[0],
    )

    circuit_breaker_max_failures: int | None = Field(
        default=None,
        title="Порог circuit breaker",
        ge=0,
        description="Переопределение количества неуспешных попыток до открытия circuit breaker",
        examples=[5],
    )

    circuit_breaker_reset_timeout: int | None = Field(
        default=None,
        title="Сброс circuit breaker",
        ge=0,
        description="Переопределение времени сброса circuit breaker",
        examples=[30],
    )

    slow_query_threshold: float | None = Field(
        default=None,
        title="Порог медленного запроса",
        ge=0,
        description="Переопределение длительности запроса для slow-query logging",
        examples=[1.0],
    )

    username: str | None = Field(
        default=None,
        title="Пользователь",
        min_length=1,
        description="Имя пользователя внешней БД, обычно подмешивается из env/Vault",
        exclude=True,
        repr=False,
        examples=["ext_user"],
    )

    password: SecretStr | None = Field(
        default=None,
        title="Пароль",
        description="Пароль пользователя внешней БД, обычно подмешивается из env/Vault",
        exclude=True,
        repr=False,
    )

    @model_validator(mode="after")
    def validate_database_target(self) -> "ExternalDatabaseItemSettings":
        """Проверяет обязательные поля для конкретного типа СУБД."""
        if self.type == DatabaseTypeChoices.oracle:
            if not self.sid and not self.service_name:
                raise ValueError("Для Oracle необходимо указать sid или service_name")
            if self.sid and self.service_name:
                raise ValueError(
                    "Для Oracle можно указать только одно из полей: sid или service_name"
                )
            if self.db_name is not None:
                raise ValueError("Поле db_name не используется для Oracle-подключения")

        if self.type == DatabaseTypeChoices.postgresql:
            if not self.db_name:
                raise ValueError("Для PostgreSQL необходимо указать db_name")
            if self.sid is not None or self.service_name is not None:
                raise ValueError(
                    "Поля sid и service_name не используются для PostgreSQL"
                )

        if self.ssl_mode and self.type != DatabaseTypeChoices.postgresql:
            raise ValueError("SSL доступен только для PostgreSQL")

        return self

    @computed_field(description="Ключ env для username")
    def username_env_key(self) -> str:
        """Возвращает имя env-переменной для username."""
        normalized = sub(r"[^A-Za-z0-9]+", "_", self.profile_name).strip("_")
        return f"EXT_DB_{normalized.upper()}_USERNAME"

    @computed_field(description="Ключ env для password")
    def password_env_key(self) -> str:
        """Возвращает имя env-переменной для password."""
        normalized = sub(r"[^A-Za-z0-9]+", "_", self.profile_name).strip("_")
        return f"EXT_DB_{normalized.upper()}_PASSWORD"


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


class ExternalDatabasesSettings(BaseSettingsWithLoader):
    """
    Настройки внешних реляционных БД.

    Структура YAML:
    external_databases:
      echo: false
      pool_size: 5
      ...
      connections:
        - name: "oracle_1"
          profile_name: "oracle_1"
          ...
    """

    yaml_group: ClassVar[str] = "external_databases"
    model_config = SettingsConfigDict(env_prefix="EXT_DB_", extra="forbid")

    echo: bool = Field(
        ...,
        description="Включить логирование SQL-запросов по умолчанию",
        examples=[False],
    )

    pool_size: int = Field(
        ...,
        title="Размер пула",
        ge=1,
        description="Максимальное количество активных соединений по умолчанию",
        examples=[5],
    )

    max_overflow: int = Field(
        ...,
        title="Доп. соединения",
        ge=0,
        description="Максимум временных соединений поверх пула по умолчанию",
        examples=[5],
    )

    pool_recycle: int = Field(
        ..., description="Интервал обновления подключения по умолчанию", examples=[1800]
    )

    pool_timeout: int = Field(
        ..., description="Таймаут ожидания пула подключений по умолчанию", examples=[30]
    )

    connect_timeout: int = Field(
        ...,
        title="Таймаут подключения",
        ge=1,
        description="Максимальное время установки соединения по умолчанию",
        examples=[10],
    )

    command_timeout: int = Field(
        ...,
        description="Максимальное время выполнения запроса по умолчанию",
        examples=[30],
    )

    ssl_mode: str | None = Field(
        default=None,
        title="Режим SSL",
        description="Настройки шифрования соединения по умолчанию",
        examples=["prefer"],
    )

    ca_bundle: str | None = Field(
        default=None,
        description="Путь к сертификату по умолчанию",
        examples=["/path/to/ca.crt"],
    )

    max_retries: int = Field(
        ...,
        ge=0,
        description="Максимальное число повторных попыток по умолчанию",
        examples=[0],
    )

    circuit_breaker_max_failures: int = Field(
        ...,
        ge=0,
        description="Максимальное количество неуспешных попыток выполнения по умолчанию",
        examples=[5],
    )

    circuit_breaker_reset_timeout: int = Field(
        ...,
        ge=0,
        description="Таймаут сброса неудачных попыток по умолчанию",
        examples=[30],
    )

    slow_query_threshold: float = Field(
        ..., ge=0, description="Порог медленного запроса по умолчанию", examples=[1.0]
    )

    connections: list[ExternalDatabaseItemSettings] = Field(
        default_factory=list,
        title="Внешние подключения",
        description="Список конфигураций внешних подключений",
    )

    @model_validator(mode="after")
    def validate_unique_profiles(self) -> "ExternalDatabasesSettings":
        """Проверяет уникальность profile_name."""
        profiles = [connection.profile_name for connection in self.connections]
        duplicates = {name for name in profiles if profiles.count(name) > 1}

        if duplicates:
            raise ValueError(
                f"Найдены повторяющиеся profile_name: {sorted(duplicates)}"
            )

        return self

    @staticmethod
    def _normalize_profile_name(profile_name: str) -> str:
        """
        Нормализует profile_name для env-переменных.

        Пример:
            oracle-1 -> ORACLE_1
            oracle_1 -> ORACLE_1
        """
        normalized = sub(r"[^A-Za-z0-9]+", "_", profile_name).strip("_")
        return normalized.upper()

    def _get_secret_from_env(self, profile_name: str, field_name: str) -> str | None:
        """
        Получает значение секрета из env.

        Формат:
            EXT_DB_<PROFILE_NAME>_<FIELD_NAME>
        """
        normalized_profile = self._normalize_profile_name(profile_name)
        env_key = f"EXT_DB_{normalized_profile}_{field_name.upper()}"
        value = getenv(env_key)

        if value is None or value == "":
            return None

        return value

    def _resolve_connection(
        self, connection: ExternalDatabaseItemSettings
    ) -> ExternalDatabaseConnectionSettings:
        """
        Собирает итоговую конфигурацию подключения:
        - берёт top-level defaults;
        - применяет profile-specific overrides;
        - подмешивает username/password из env.
        """
        payload = connection.model_dump(exclude_none=True)

        common_fields = (
            "echo",
            "pool_size",
            "max_overflow",
            "pool_recycle",
            "pool_timeout",
            "connect_timeout",
            "command_timeout",
            "ssl_mode",
            "ca_bundle",
            "max_retries",
            "circuit_breaker_max_failures",
            "circuit_breaker_reset_timeout",
            "slow_query_threshold",
        )

        for field_name in common_fields:
            if field_name not in payload:
                payload[field_name] = getattr(self, field_name)

        username = connection.username or self._get_secret_from_env(
            connection.profile_name, "username"
        )
        password_raw = (
            connection.password.get_secret_value()
            if connection.password is not None
            else self._get_secret_from_env(connection.profile_name, "password")
        )

        if connection.enabled and not username:
            raise ValueError(
                f"Не найден username для внешней БД '{connection.profile_name}'"
            )

        if connection.enabled and not password_raw:
            raise ValueError(
                f"Не найден password для внешней БД '{connection.profile_name}'"
            )

        payload["username"] = username
        payload["password"] = SecretStr(password_raw) if password_raw else None

        return ExternalDatabaseConnectionSettings(**payload)

    @computed_field(description="Словарь активных подключений по profile_name")
    def profiles(self) -> dict[str, ExternalDatabaseConnectionSettings]:
        """Возвращает словарь активных подключений по profile_name."""
        result: dict[str, ExternalDatabaseConnectionSettings] = {}

        for connection in self.connections:
            if not connection.enabled:
                continue

            result[connection.profile_name] = self._resolve_connection(connection)

        return result

    def get_profile(self, profile_name: str) -> ExternalDatabaseConnectionSettings:
        """
        Возвращает resolved-конфигурацию внешней БД по profile_name.
        """
        try:
            return self.profiles[profile_name]  # type: ignore[index]
        except KeyError as exc:
            raise ValueError(f"Профиль внешней БД '{profile_name}' не найден") from exc


external_databases_settings = ExternalDatabasesSettings()
