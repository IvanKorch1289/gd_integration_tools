from __future__ import annotations

from typing import ClassVar
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, computed_field, field_serializer, model_validator
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.base import mask_url_password
from src.backend.core.config.config_loader import BaseSettingsWithLoader
from src.backend.core.config.db_drivers import ensure_driver_available
from src.backend.core.enums.database import DatabaseTypeChoices

__all__ = ("DatabaseConnectionSettings", "db_connection_settings")


class DatabaseConnectionSettings(BaseSettingsWithLoader):
    """Настройки подключения к реляционным базам данных.

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
        default="psycopg",
        description=(
            "Пакет синхронного драйвера. Для sqlite используется встроенный "
            "'pysqlite'. По умолчанию — psycopg3 (psycopg): умеет и sync, "
            "и async, в отличие от драйвера v2, которого нет в проекте."
        ),
        examples=["psycopg", "oracledb", "pysqlite"],
    )

    echo: bool = Field(default=False)

    username: str = Field(
        default="",
        title="Пользователь",
        description="Имя пользователя для аутентификации. Игнорируется для sqlite.",
        examples=["app_user"],
    )

    password: SecretStr | None = Field(
        default=None,
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

    pool_pre_ping: bool = Field(
        default=True,
        title="Pool pre-ping",
        description=(
            "Sprint 6 K2: SQLAlchemy ``pool_pre_ping`` (V15 R-V15-14). При "
            "True перед выдачей connection из pool выполняется лёгкий ping "
            "(SELECT 1) для отсева умерших соединений. Рекомендован для "
            "production (нагрузочные DB через proxy/load-balancer). На dev_light "
            "можно отключить для убыстрения startup."
        ),
        examples=[True],
    )

    pool_use_lifo: bool = Field(
        default=True,
        title="Pool LIFO order",
        description=(
            "Sprint 6 K2: SQLAlchemy ``pool_use_lifo=True`` использует "
            "недавно освобождённый connection (вместо FIFO). Под нагрузкой "
            "снижает количество одновременных активных connections и "
            "уменьшает recycle pressure."
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

    replica_dsn: str | None = Field(
        default=None,
        title="DSN read-replica",
        description=(
            "S11 K2 W2: явный async DSN для read-only replica. Если задан, "
            ":class:`SmartSessionManager` направляет read-only сессии сюда, "
            "снижая нагрузку на primary в 2–3x для read-heavy workload. "
            "Если None, replica-роутинг отключён и все запросы идут на primary."
        ),
        examples=["postgresql+asyncpg://user:pwd@replica.db:5432/app"],
    )

    @computed_field(repr=False, description="URL асинхронного подключения")
    def async_connection_url(self) -> str:
        """Формирует DSN для асинхронного драйвера."""
        return self._build_dsn(is_async=True)

    @computed_field(repr=False, description="URL синхронного подключения")
    def sync_connection_url(self) -> str:
        """Формирует DSN для синхронного драйвера."""
        return self._build_dsn(is_async=False)

    @field_serializer("async_connection_url", "sync_connection_url")
    def _serialize_connection_urls(self, value: str) -> str:
        """Маскирует пароль в дампе модели (ADR-0378).

        ``repr=False`` скрывает DSN только из ``__repr__`` — в
        ``model_dump()``/``model_dump_json()`` пароль утекал открытым
        текстом. Атрибуты DSN остаются рабочими: SQLAlchemy подключается
        с настоящим паролем.
        """
        return mask_url_password(value)

    def _build_dsn(self, is_async: bool) -> str:
        """Внутренний метод генерации строки подключения.

        Примечание:
            Для Oracle поле `name` трактуется как `service_name`.
            Для SQLite используется ``path`` (для ``:memory:`` префикс пустой).
            Для MSSQL/MySQL/DB2 — S104 W3 добавлена поддержка.

        Wave 13 Q9: перед сборкой DSN драйвер проверяется на
        объявленность/наличие (``ensure_driver_available``) — иначе
        неразрешимый драйвер падал бы в рантайме как ``ModuleNotFoundError``
        внутри SQLAlchemy.
        """
        if self.type == DatabaseTypeChoices.sqlite:
            driver = "aiosqlite" if is_async else "pysqlite"
            ensure_driver_available(driver)
            target = self.path or ":memory:"
            return f"sqlite+{driver}:///{target}"

        driver = self.async_driver if is_async else self.sync_driver
        ensure_driver_available(driver)

        # Cycle 172 (HIGH-13): логин и пароль интерполировались в DSN сырым.
        # Пароль с ``@ : / # ? %`` ломал строку подключения — SQLAlchemy
        # разбирал её как другой хост/путь. Внешний контур уже использовал
        # ``quote_plus`` (``external_databases/connection.py``) — основной
        # теперь приведён к тому же поведению.
        username = quote_plus(self.username)
        secret = self.password.get_secret_value() if self.password else ""
        password = quote_plus(secret)

        if self.type == DatabaseTypeChoices.postgresql:
            return (
                f"postgresql+{driver}://{username}:{password}"
                f"@{self.host}:{self.port}/{self.name}"
            )

        if self.type == DatabaseTypeChoices.oracle:
            return (
                f"oracle+{driver}://{username}:{password}"
                f"@{self.host}:{self.port}/?service_name={self.name}"
            )

        # S104 W3: MSSQL / MySQL / DB2 support (DEEP-RESEARCH D19).
        if self.type == DatabaseTypeChoices.mssql:
            # pyodbc / aioodbc — ODBC driver. ``aioodbc`` объявлен в extra
            # ``db_drivers``; ``pyodbc`` (sync) в extras НЕ объявлен —
            # сборка DSN с ним отвергается ``ensure_driver_available``
            # (см. core/config/db_drivers.py и owner-задачу Sprint 36).
            mssql_driver = driver or ("aioodbc" if is_async else "pyodbc")
            return (
                f"mssql+{mssql_driver}://{username}:{password}"
                f"@{self.host}:{self.port}/{self.name}"
                f"?driver=ODBC+Driver+17+for+SQL+Server"
            )

        if self.type == DatabaseTypeChoices.mysql:
            # aiomysql / pymysql. Требует ``aiomysql`` (async) или ``pymysql`` (sync).
            mysql_driver = driver or ("aiomysql" if is_async else "pymysql")
            return (
                f"mysql+{mysql_driver}://{username}:{password}"
                f"@{self.host}:{self.port}/{self.name}"
            )

        if self.type == DatabaseTypeChoices.db2:
            # ibm_db / ibm_db_sa. Требует ``ibm_db`` или ``ibm_db_sa``.
            db2_driver = driver or "ibm_db_sa"
            return (
                f"db2+{db2_driver}://{username}:{password}"
                f"@{self.host}:{self.port}/{self.name}"
            )

        # S168 W10 P1-8: ClickHouse support (analytics path).
        # ClickHouse НЕ использует SQLAlchemy ORM fabric — он
        # аналитическая column-store с другим protocol (HTTP/TCP).
        # ``clickhouse_connect`` предоставляет async client напрямую
        # (см. infrastructure/clients/storage/clickhouse.py).
        # Здесь мы только сигнализируем support: factory/dialect
        # роутинг отделён, реальная интеграция — отдельный WIP.
        if self.type == DatabaseTypeChoices.clickhouse:
            # placeholder URL: не используется SQLAlchemy, но сигнализирует
            # ``is_async=True`` для downstream dialector.
            return (
                f"clickhouse://{quote_plus(self.username)}:"
                f"{quote_plus(secret)}"
                f"@{self.host}:{self.port}/{self.name}"
            )

        raise NotImplementedError(f"Поддержка СУБД '{self.type}' не реализована")

    @model_validator(mode="after")
    def validate_ssl(self) -> DatabaseConnectionSettings:
        """Проверяет корректность SSL-настроек."""
        if self.ssl_mode and self.type != DatabaseTypeChoices.postgresql:
            raise ValueError("SSL доступен только для PostgreSQL")
        return self

    @model_validator(mode="after")
    def validate_oracle_drivers(self) -> DatabaseConnectionSettings:
        """Для Oracle драйверы PG-семейства не работают.

        В ``base.yml`` зашиты PG-defaults ``asyncpg``/``psycopg``. При
        переключении профиля на Oracle их обязательно переопределить в
        overlay (``async_driver=oracledb``, ``sync_driver=oracledb``);
        иначе DSN строится с неверным префиксом и падает в рантайме.
        """
        if self.type == DatabaseTypeChoices.oracle:
            invalid = {"asyncpg", "psycopg"}
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
    def validate_required_fields(self) -> DatabaseConnectionSettings:
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
