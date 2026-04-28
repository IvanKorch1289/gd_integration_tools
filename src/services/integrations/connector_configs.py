"""Protocol ``ConnectorConfigStore`` + DTO (Wave 9.2.3).

Унифицированное хранилище конфигов внешних коннекторов в MongoDB
(коллекция ``connector_configs``). Позволяет admin-эндпоинту читать
и обновлять конфиг без рестарта приложения; в момент записи запускается
hot-reload коннектора через ``ConnectorRegistry`` (если такой есть).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("ConnectorConfigEntry", "ConnectorConfigStore")


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


@runtime_checkable
class ConnectorConfigStore(Protocol):
    """Контракт хранилища конфигов коннекторов."""

    async def get(self, name: str) -> ConnectorConfigEntry | None: ...

    async def save(
        self,
        name: str,
        config: dict[str, Any],
        *,
        enabled: bool = True,
        user: str | None = None,
    ) -> ConnectorConfigEntry: ...

    async def list_all(self) -> list[ConnectorConfigEntry]: ...

    async def delete(self, name: str) -> bool: ...

    async def ensure_indexes(self) -> None: ...
