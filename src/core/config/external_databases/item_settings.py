from re import sub

from pydantic import BaseModel, Field, SecretStr, computed_field, model_validator

from app.core.enums.database import DatabaseTypeChoices

__all__ = ("ExternalDatabaseItemSettings",)


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
