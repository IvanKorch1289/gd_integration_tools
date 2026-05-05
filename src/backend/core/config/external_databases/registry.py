from os import getenv
from re import sub
from typing import ClassVar

from pydantic import Field, SecretStr, computed_field, model_validator
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader
from src.core.config.external_databases.connection import (
    ExternalDatabaseConnectionSettings,
)
from src.core.config.external_databases.item import ExternalDatabaseItemSettings

__all__ = ("ExternalDatabasesSettings", "external_databases_settings")


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
