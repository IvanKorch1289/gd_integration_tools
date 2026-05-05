"""Protocol ``ConnectorConfigStore`` + DTO (Wave 9.2.3).

Унифицированное хранилище конфигов внешних коннекторов в MongoDB
(коллекция ``connector_configs``). Позволяет admin-эндпоинту читать
и обновлять конфиг без рестарта приложения; в момент записи запускается
hot-reload коннектора через ``ConnectorRegistry`` (если такой есть).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.backend.core.models.connector_configs import ConnectorConfigEntry

__all__ = ("ConnectorConfigEntry", "ConnectorConfigStore")


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
