"""DTO ConnectorConfigEntry (Wave 9.2.3).

Запись конфигурации внешнего коннектора в MongoDB-коллекции
``connector_configs``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("ConnectorConfigEntry",)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ConnectorConfigEntry(BaseModel):
    """DTO одной записи конфигурации коннектора."""

    model_config = ConfigDict(extra="ignore")

    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    updated_at: datetime = Field(default_factory=_utc_now)
    updated_by: str | None = None
    version: int = 1
