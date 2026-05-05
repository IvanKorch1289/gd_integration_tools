"""MongoDB-имплементация ``ConnectorConfigStore`` (Wave 9.2.3).

Коллекция ``connector_configs``. ``_id == name`` (имя коннектора).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.core.di import app_state_singleton
from src.core.models.connector_configs import ConnectorConfigEntry
from src.infrastructure.clients.storage.mongodb import MongoDBClient, get_mongo_client

__all__ = ("MongoConnectorConfigStore", "get_connector_config_store")

logger = logging.getLogger(__name__)

_COLLECTION = "connector_configs"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _doc_to_entry(doc: dict[str, Any]) -> ConnectorConfigEntry:
    payload = dict(doc)
    payload["name"] = payload.pop("_id", payload.get("name", ""))
    return ConnectorConfigEntry.model_validate(payload)


class MongoConnectorConfigStore:
    """Mongo-реализация ``ConnectorConfigStore``."""

    def __init__(self, client_factory: Any | None = None) -> None:
        self._client_factory = client_factory or get_mongo_client

    def _client(self) -> MongoDBClient:
        return self._client_factory()

    async def ensure_indexes(self) -> None:
        try:
            collection = self._client().collection(_COLLECTION)
            await collection.create_index("enabled", name="enabled_idx")
            await collection.create_index([("updated_at", -1)], name="updated_at_desc")
        except Exception as exc:  # noqa: BLE001
            logger.warning("MongoConnectorConfigStore: ensure_indexes failed: %s", exc)

    async def get(self, name: str) -> ConnectorConfigEntry | None:
        doc = await self._client().find_one(_COLLECTION, {"_id": name})
        return _doc_to_entry(doc) if doc else None

    async def save(
        self,
        name: str,
        config: dict[str, Any],
        *,
        enabled: bool = True,
        user: str | None = None,
    ) -> ConnectorConfigEntry:
        existing = await self.get(name)
        version = (existing.version + 1) if existing else 1
        entry = ConnectorConfigEntry(
            name=name,
            config=dict(config),
            enabled=enabled,
            updated_at=_utc_now(),
            updated_by=user,
            version=version,
        )
        payload = entry.model_dump(mode="json")
        payload["_id"] = payload.pop("name")
        await self._client().update_one(
            _COLLECTION, query={"_id": name}, update=payload, upsert=True
        )
        return entry

    async def list_all(self) -> list[ConnectorConfigEntry]:
        docs = await self._client().find(
            _COLLECTION, query={}, limit=1000, sort=[("updated_at", -1)]
        )
        return [_doc_to_entry(d) for d in docs]

    async def delete(self, name: str) -> bool:
        deleted = await self._client().delete_one(_COLLECTION, {"_id": name})
        return deleted > 0


@app_state_singleton("connector_config_store", factory=MongoConnectorConfigStore)
def get_connector_config_store() -> MongoConnectorConfigStore:
    """Singleton ``MongoConnectorConfigStore``."""
