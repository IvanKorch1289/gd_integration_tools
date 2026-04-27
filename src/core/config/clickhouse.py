"""Настройки подключения к ClickHouse."""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader

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


clickhouse_settings = ClickHouseSettings()
