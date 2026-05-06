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

    # ── Persistent connection pool (httpx.Limits + lifecycle) ──
    pool_size: int = Field(
        20,
        ge=1,
        description="Макс. одновременных HTTP-соединений в пуле (httpx Limits.max_connections).",
    )
    pool_overflow: int = Field(
        10,
        ge=0,
        description="Доп. keep-alive соединения сверх pool_size (Limits.max_keepalive_connections дельта).",
    )
    keepalive_expiry: float = Field(
        30.0,
        gt=0,
        description="Сек. жизни keep-alive соединения (Limits.keepalive_expiry).",
    )
    recycle_seconds: int = Field(
        3600,
        ge=60,
        description="TTL HTTP-клиента (сек): по истечении соединения пересоздаются.",
    )
    pool_pre_ping: bool = Field(
        True,
        description="Health-check (/ping) перед использованием соединения после простоя.",
    )
    max_connections: int = Field(
        100,
        ge=1,
        description="Жёсткий cap на общее число соединений (sanity-limit).",
    )


clickhouse_settings = ClickHouseSettings()
