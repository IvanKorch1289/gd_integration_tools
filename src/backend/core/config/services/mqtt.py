"""MQTT Settings — настройки MQTT-брокера.

Перенесено из entrypoints/mqtt/mqtt_handler.py для устранения
layer violation: infrastructure/ → entrypoints/.

См. ADR-NEW-X: MqttSettings migration to core/config.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("MqttSettings",)

mqtt_settings: MqttSettings
"""Глобальный экземпляр MqttSettings."""


class MqttSettings(BaseSettingsWithLoader):
    """Настройки MQTT-брокера."""

    yaml_group: ClassVar[str] = "mqtt"
    model_config = SettingsConfigDict(env_prefix="MQTT_", extra="forbid")

    broker_host: str = Field(default="localhost", description="Хост MQTT-брокера")
    broker_port: int = Field(
        default=1883, ge=1, le=65535, description="Порт MQTT-брокера"
    )
    username: str = Field(default="", description="Имя пользователя")
    password: str = Field(default="", description="Пароль")
    client_id: str = Field(
        default="gd-integration-tools", description="Client ID для MQTT"
    )
    topics: list[str] = Field(
        default_factory=lambda: ["gd/#"],
        description="Топики для подписки (поддерживаются wildcards + и #)",
    )
    qos: int = Field(default=1, ge=0, le=2, description="Quality of Service (0, 1, 2)")
    enabled: bool = Field(default=True, description="Включить MQTT-подсистему"),  # S171 M9: enable (project not in prod)

    # TLS / mTLS (A2 / ADR-004). Для prod/внешних брокеров TLS обязателен.
    tls_enabled: bool = Field(
        default=False,         description="Включить TLS для MQTT (обязательно для публичных брокеров)",
    )
    ca_cert_path: str = Field(
        default="", description="Путь к CA-сертификату брокера (PEM)"
    )
    client_cert_path: str = Field(
        default="", description="Путь к клиентскому сертификату (для mTLS)"
    )
    client_key_path: str = Field(
        default="", description="Путь к клиентскому ключу (для mTLS)"
    )


mqtt_settings = MqttSettings()
