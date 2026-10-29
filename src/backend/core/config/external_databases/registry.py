from __future__ import annotations

from os import getenv
from re import sub
from typing import ClassVar

from pydantic import Field, SecretStr, computed_field, model_validator
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader
from src.backend.core.config.external_databases.connection import (
    ExternalDatabaseConnectionSettings,
)
from src.backend.core.config.external_databases.item import ExternalDatabaseItemSettings
from src.backend.core.logging import get_logger

__all__ = ("ExternalDatabasesSettings", "external_databases_settings")

_logger = get_logger("config.external_databases")


class ExternalDatabasesSettings(BaseSettingsWithLoader):
    """Настройки внешних реляционных БД.

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

    pool_pre_ping: bool = Field(
        default=True,
        title="Pool pre-ping (default)",
        description=(
            "Sprint 6 K2: SQLAlchemy ``pool_pre_ping`` default для всех "
            "external_databases connections. Может переопределяться "
            "per-connection через ExternalDatabaseItemSettings."
        ),
        examples=[True],
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
    def validate_unique_profiles(self) -> ExternalDatabasesSettings:
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
        """Нормализует profile_name для env-переменных.

        Пример:
            oracle-1 -> ORACLE_1
            oracle_1 -> ORACLE_1
        """
        normalized = sub(r"[^A-Za-z0-9]+", "_", profile_name).strip("_")
        return normalized.upper()

    def _get_secret_from_env(self, profile_name: str, field_name: str) -> str | None:
        """Получает значение секрета из env.

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
        """Собирает итоговую конфигурацию подключения:
        - берёт top-level defaults;
        - применяет profile-specific overrides;
        - подмешивает username/password из env.

        ADR-0385 (A8): отсутствие кредов НЕ поднимает исключение — иначе
        computed-поля роняли ``settings.model_dump()`` и admin-эндпоинт
        ``GET /api/v1/admin/config`` отдавал 500. Проблема фиксируется
        warning'ом и проявляется в момент реального использования
        профиля (:meth:`get_profile`).
        """
        # ``exclude`` — computed-поля item'а (``username_env_key``/
        # ``password_env_key``): это служебные ключи env, а не параметры
        # подключения (ADR-0385 A10: item — extra="forbid", лишние ключи
        # отвергаются валидатором).
        payload = connection.model_dump(
            exclude_none=True,
            exclude=set(ExternalDatabaseItemSettings.model_computed_fields),
        )

        common_fields = (
            "echo",
            "pool_size",
            "max_overflow",
            "pool_recycle",
            "pool_timeout",
            "pool_pre_ping",
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
            _logger.warning(
                "Не найден username для внешней БД '%s' — профиль деградирован "
                "(подключение невозможно до появления кредов в env/Vault)",
                connection.profile_name,
            )

        if connection.enabled and not password_raw:
            _logger.warning(
                "Не найден password для внешней БД '%s' — профиль деградирован "
                "(подключение невозможно до появления кредов в env/Vault)",
                connection.profile_name,
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
        """Возвращает resolved-конфигурацию внешней БД по profile_name.

        Raises:
            ValueError: Профиля нет либо для него не заданы креды
                (fail-fast в точке использования — вместо молчаливого
                подключения без пароля).

        """
        try:
            connection = self.profiles[profile_name]  # type: ignore[index]
        except KeyError as exc:
            raise ValueError(f"Профиль внешней БД '{profile_name}' не найден") from exc
        if not connection.username or connection.password is None:
            raise ValueError(
                f"Не найден username/password для внешней БД '{profile_name}'"
            )
        return connection


external_databases_settings = ExternalDatabasesSettings()
