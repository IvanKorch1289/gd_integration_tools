from pathlib import Path
from typing import Any, ClassVar

from pydantic import Field, computed_field, field_validator
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader


class MailSettings(BaseSettingsWithLoader):
    """
    Настройки конфигурации для сервиса электронной почты.

    Этот класс содержит параметры для настройки SMTP сервера, аутентификации, таймаутов и других параметров,
    связанных с отправкой электронной почты.
    """

    yaml_group: ClassVar[str] = "mail"
    model_config = SettingsConfigDict(env_prefix="MAIL_", extra="forbid")

    # Блок настроек SMTP сервера
    host: str = Field(
        ..., description="Имя хоста SMTP сервера", json_schema_extra={"example": "smtp.example.com"}
    )
    port: int = Field(
        ..., ge=1, le=65535, description="Номер порта SMTP сервера", json_schema_extra={"example": 587}
    )
    use_tls: bool = Field(
        ..., description="Включить STARTTLS для безопасных соединений", json_schema_extra={"example": True}
    )
    validate_certs: bool = Field(
        ..., description="Проверять SSL/TLS сертификаты сервера", json_schema_extra={"example": True}
    )
    ca_bundle: Path | None = Field(
        ...,
        description="Путь к пользовательскому пакету CA сертификатов",
        json_schema_extra={"example": "/path/to/ca_bundle.crt"},
    )

    # Блок настроек аутентификации
    username: str = Field(
        ...,
        description="Имя пользователя для аутентификации SMTP",
        json_schema_extra={"example": "user@example.com"},
    )
    password: str = Field(
        ..., description="Пароль для аутентификации SMTP", json_schema_extra={"example": "securepassword123"}
    )

    # Блок настроек таймаутов и пула соединений
    connection_pool_size: int = Field(
        ..., ge=1, le=20, description="Размер пула соединений SMTP", json_schema_extra={"example": 5}
    )
    connect_timeout: int = Field(
        ..., ge=5, le=30, description="Таймаут подключения в секундах", json_schema_extra={"example": 30}
    )
    command_timeout: int = Field(
        ..., ge=5, le=300, description="Таймаут сетевой операции в секундах", json_schema_extra={"example": 30}
    )

    # Блок настроек отправителя и шаблонов
    sender: str = Field(
        ...,
        description="Адрес электронной почты отправителя по умолчанию",
        json_schema_extra={"example": "noreply@example.com"},
    )
    template_folder: Path | None = Field(
        ...,
        description="Путь к директории с шаблонами писем",
        json_schema_extra={"example": "/app/email_templates"},
    )

    # Блок настроек Circuit Breaker
    circuit_breaker_max_failures: int = Field(
        ...,
        ge=0,
        description="Максимальное количество сбоев до срабатывания Circuit Breaker",
        json_schema_extra={"example": 5},
    )
    circuit_breaker_reset_timeout: int = Field(
        ...,
        ge=0,
        description="Время (в секундах) до сброса Circuit Breaker",
        json_schema_extra={"example": 60},
    )

    @computed_field(description="URL почтового сервера")
    def smtp_url(self) -> str:
        """Сформировать URL для подключения к почтовомуу серверу."""
        return f"{'https://' if self.use_tls else 'http://'}{self.host}"

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int, values: Any) -> int:
        if v == 465 and not values.data.get("use_tls"):
            raise ValueError("Порт 465 требует включения SSL/TLS")
        return v

    @field_validator("ca_bundle")
    @classmethod
    def validate_ca_path(cls, v: Path | None) -> Path | None:
        if v and not v.exists():
            raise ValueError(f"Файл CA bundle не найден: {v}")
        return v


mail_settings = MailSettings()
"""Глобальные настройки подключения SMTP-сервера"""
