"""Настройки подключения к ClickHouse."""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("ClickHouseSettings", "clickhouse_settings")


class ClickHouseSettings(BaseSettingsWithLoader):
    """Конфигурация подключения к ClickHouse."""

    yaml_group: ClassVar[str] = "clickhouse"
    model_config = SettingsConfigDict(env_prefix="CLICKHOUSE_", extra="forbid")

    host: str = Field("localhost", description="Хост ClickHouse.")
    port: int = Field(9000, gt=0, lt=65536, description="Порт ClickHouse (native).")
    http_port: int = Field(8123, gt=0, lt=65536, description="HTTP-порт ClickHouse.")
    database: str = Field("default", description="Имя базы данных.")
    user: str = Field("default", description="Пользователь.")
    password: str = Field("", description="Пароль.")
    secure: bool = Field(False, description="Использовать TLS.")
    connect_timeout: int = Field(10, ge=1, description="Таймаут подключения (сек).")
    send_receive_timeout: int = Field(300, ge=1, description="Таймаут операций (сек).")
    max_batch_size: int = Field(10000, ge=1, description="Макс. размер batch insert.")
    enabled: bool = Field(False, description="Включить ClickHouse интеграцию.")

    # R-V15-14: connection pool параметры для httpx.Limits.
    # pool_size — общий лимит соединений в pool'е;
    # max_keepalive_connections — сколько idle TCP-соединений держать
    # для reuse; keepalive_expiry — TTL idle-соединения (сек).
    pool_size: int = Field(
        20,
        ge=1,
        description="Макс. число соединений в HTTP pool (httpx.Limits.max_connections).",
    )
    max_keepalive_connections: int = Field(
        10,
        ge=0,
        description="Idle TCP-соединения для reuse (httpx.Limits.max_keepalive_connections).",
    )
    keepalive_expiry: float = Field(
        30.0,
        ge=0.0,
        description="TTL idle-соединения в секундах (httpx.Limits.keepalive_expiry).",
    )


clickhouse_settings = ClickHouseSettings()
