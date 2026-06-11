"""Lineage-настройки для OpenLineage HTTP emitter."""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("LineageSettings", "lineage_settings")


class LineageSettings(BaseSettingsWithLoader):
    """Конфигурация OpenLineage / Marquez emitter'а."""

    yaml_group: ClassVar[str] = "lineage"
    model_config = SettingsConfigDict(env_prefix="LINEAGE_", extra="forbid")

    url: str = Field(
        default="http://marquez:5000",
        description="URL OpenLineage-совместимого сервера (Marquez).",
    )
    namespace: str = Field(
        default="gd_integration_tools",
        description="Namespace для lineage событий.",
    )
    timeout_s: float = Field(
        default=5.0,
        ge=0.1,
        description="HTTP-таймаут для POST batch'ей (сек).",
    )
    batch_size: int = Field(
        default=100,
        ge=1,
        description="Размер batch'а перед flush.",
    )
    max_queue: int = Field(
        default=10_000,
        ge=1,
        description="Максимальный размер in-memory очереди событий.",
    )
    auth_token: str | None = Field(
        default=None,
        description="Опциональный Bearer-токен для авторизации.",
    )


lineage_settings = LineageSettings()
