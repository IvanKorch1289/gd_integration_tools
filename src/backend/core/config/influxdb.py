"""InfluxDB-настройки для TimeSeriesWriteProcessor."""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("InfluxDBSettings", "influxdb_settings")


class InfluxDBSettings(BaseSettingsWithLoader):
    """Конфигурация InfluxDB клиента."""

    yaml_group: ClassVar[str] = "influxdb"
    model_config = SettingsConfigDict(env_prefix="INFLUXDB_", extra="forbid")

    url: str = Field(
        default="http://localhost:8086", description="HTTP URL InfluxDB-сервера."
    )
    token: str = Field(default="", description="InfluxDB API-токен.")
    org: str = Field(default="default", description="InfluxDB организация.")
    bucket: str = Field(
        default="metrics", description="Bucket по умолчанию для записи."
    )


influxdb_settings = InfluxDBSettings()
