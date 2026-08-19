from typing import ClassVar, Literal

from pydantic import Field, computed_field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader


class LogStorageSettings(BaseSettingsWithLoader):
    """Настройки для системы логирования и хранения логов."""

    yaml_group: ClassVar[str] = "log"
    model_config = SettingsConfigDict(env_prefix="LOG_", extra="forbid")

    # Параметры подключения
    host: str = Field(
        ...,
        description="Хост сервера логов",
        json_schema_extra={"example": "logs.example.com"},
    )
    port: int = Field(
        ...,
        gt=0,
        lt=65536,
        description="TCP-порт сервера логов",
        json_schema_extra={"example": 514},
    )
    udp_port: int = Field(
        ...,
        gt=0,
        lt=65536,
        description="UDP-порт для отправки логов",
        json_schema_extra={"example": 514},
    )

    # Параметры безопасности
    use_tls: bool = Field(
        ...,
        description="Использовать TLS для безопасных подключений",
        json_schema_extra={"example": True},
    )
    ca_bundle: str | None = Field(
        default=None,
        description="Путь к пакету CA-сертификатов",
        json_schema_extra={"example": "/path/to/ca-bundle.crt"},
    )

    # Параметры логирования
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        ...,
        pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$",
        description="Уровень детализации логирования",
        json_schema_extra={"example": "INFO"},
    )
    name_log_file: str = Field(
        ..., description="Путь к файлу логов", json_schema_extra={"example": "app.log"}
    )
    dir_log_name: str = Field(
        ...,
        description="Имя директории для хранения логов",
        json_schema_extra={"example": "/var/logs/myapp"},
    )
    required_fields: list[str] = Field(
        ...,
        default_factory=list,
        min_length=1,
        description="Обязательные поля в лог-сообщениях",
        json_schema_extra={"example": {"timestamp", "level", "message"}},
    )
    log_requests: bool = Field(
        ...,
        description="Включить логирование входящих запросов",
        json_schema_extra={"example": True},
    )
    max_body_log_size: int = Field(
        ...,
        description="Максимальный размер лог-сообщений для логирования в байтах",
        json_schema_extra={"example": 1024 * 1024},  # 1MB
    )

    # Конфигурация логгеров
    conf_loggers: list[dict] = Field(
        ...,
        default_factory=list,
        min_length=1,
        description="Конфигурация логгеров",
        json_schema_extra={
            "example": [{"name": "application", "facility": "application"}]
        },
    )

    @computed_field
    def base_url(self) -> str:
        """Создает нормализованную строку эндпоинта."""
        return f"{'https://' if self.use_tls else 'http://'}{self.host}:{self.port}"


log_settings = LogStorageSettings()
"""Глобальные настройки логирования"""
