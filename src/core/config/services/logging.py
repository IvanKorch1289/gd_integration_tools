from typing import ClassVar, Literal

from pydantic import Field, computed_field
from pydantic_settings import SettingsConfigDict

from app.core.config.config_loader import BaseSettingsWithLoader


class LogStorageSettings(BaseSettingsWithLoader):
    """Настройки для системы логирования и хранения логов."""

    yaml_group: ClassVar[str] = "log"
    model_config = SettingsConfigDict(env_prefix="LOG_", extra="forbid")

    # Параметры подключения
    host: str = Field(..., description="Хост сервера логов", example="logs.example.com")
    port: int = Field(
        ..., gt=0, lt=65536, description="TCP-порт сервера логов", example=514
    )
    udp_port: int = Field(
        ..., gt=0, lt=65536, description="UDP-порт для отправки логов", example=514
    )

    # Параметры безопасности
    use_tls: bool = Field(
        ..., description="Использовать TLS для безопасных подключений", example=True
    )
    ca_bundle: str | None = Field(
        default=None,
        description="Путь к пакету CA-сертификатов",
        example="/path/to/ca-bundle.crt",
    )

    # Параметры логирования
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        ...,
        pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$",
        description="Уровень детализации логирования",
        example="INFO",
    )
    name_log_file: str = Field(..., description="Путь к файлу логов", example="app.log")
    dir_log_name: str = Field(
        ..., description="Имя директории для хранения логов", example="/var/logs/myapp"
    )
    required_fields: list[str] = Field(
        ...,
        default_factory=list,
        min_items=1,
        description="Обязательные поля в лог-сообщениях",
        example={"timestamp", "level", "message"},
    )
    log_requests: bool = Field(
        ..., description="Включить логирование входящих запросов", example=True
    )
    max_body_log_size: int = Field(
        ...,
        description="Максимальный размер лог-сообщений для логирования в байтах",
        example=1024 * 1024,  # 1MB
    )

    # Конфигурация логгеров
    conf_loggers: list[dict] = Field(
        ...,
        default_factory=list,
        min_items=1,
        description="Конфигурация логгеров",
        example=[{"name": "application", "facility": "application"}],
    )

    @computed_field
    def base_url(self) -> str:
        """Создает нормализованную строку эндпоинта."""
        return f"{'https://' if self.use_tls else 'http://'}{self.host}:{self.port}"


log_settings = LogStorageSettings()
"""Глобальные настройки логирования"""
