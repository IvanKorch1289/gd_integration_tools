"""Mongo-проекция состояний workflow (Wave 9.2.2).

Postgres остаётся source-of-truth (ACID); MongoDB — eventually consistent
read-only view для UI/observability без джойнов и nested-навигации по
дереву шагов. Коллекция ``workflow_state``: документ на инстанс по
``_id == str(workflow_id)``.

TTL по ``finished_at`` (90 дней) с partialFilterExpression — чистятся
только terminal-инстансы; running остаются в Mongo столько, сколько
живут в Postgres.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.backend.core.di import app_state_singleton
from src.backend.infrastructure.clients.storage.mongodb import (
    MongoDBClient,
    get_mongo_client,
)

__all__ = ("WorkflowStateProjector", "get_workflow_state_projector")

logger = logging.getLogger(__name__)

_COLLECTION = "workflow_state"
_TTL_SECONDS = 90 * 86400


class WorkflowStateProjector:
    """Пишет читательскую проекцию ``WorkflowInstance`` в MongoDB."""

    def __init__(self, client_factory: Any | None = None) -> None:
        self._client_factory = client_factory or get_mongo_client

    def _client(self) -> MongoDBClient:
        return self._client_factory()

    async def ensure_indexes(self) -> None:
        try:
            collection = self._client().collection(_COLLECTION)
            await collection.create_index(
                [("tenant_id", 1), ("status", 1)], name="tenant_status"
            )
            await collection.create_index(
                [("route_id", 1), ("updated_at", -1)], name="route_updated"
            )
            await collection.create_index([("updated_at", -1)], name="updated_at_desc")
            await collection.create_index(
                "finished_at",
                name="ttl_finished_at",
                expireAfterSeconds=_TTL_SECONDS,
                partialFilterExpression={"finished_at": {"$exists": True}},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("WorkflowStateProjector: ensure_indexes failed: %s", exc)

    async def sync(
        self,
        *,
        workflow_id: UUID,
        snapshot_state: dict[str, Any] | None,
        status: str,
        route_id: str,
        tenant_id: str,
        workflow_name: str,
        updated_at: datetime,
        finished_at: datetime | None = None,
    ) -> None:
        """Upsert документа в коллекцию ``workflow_state``."""
        update: dict[str, Any] = {
            "snapshot": snapshot_state or {},
            "status": status,
            "route_id": route_id,
            "tenant_id": tenant_id,
            "workflow_name": workflow_name,
            "updated_at": updated_at.isoformat(),
        }
        if finished_at is not None:
            update["finished_at"] = finished_at.isoformat()
        try:
            await self._client().update_one(
                _COLLECTION, query={"_id": str(workflow_id)}, update=update, upsert=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "WorkflowStateProjector.sync failed for %s: %s", workflow_id, exc
            )

    async def sync_fire_and_forget(self, **kwargs: Any) -> None:
        """Не блокирует caller — отправляет sync через ``asyncio.create_task``."""
        try:
            asyncio.create_task(self.sync(**kwargs))
        except RuntimeError:
            # Нет работающего event loop — пропускаем (вне FastAPI lifespan).
            return

    async def get(self, workflow_id: UUID) -> dict[str, Any] | None:
        return await self._client().find_one(_COLLECTION, {"_id": str(workflow_id)})

    async def list_by_tenant(
        self, tenant_id: str, *, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"tenant_id": tenant_id}
        if status is not None:
            query["status"] = status
        return await self._client().find(
            _COLLECTION, query=query, limit=limit, sort=[("updated_at", -1)]
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@app_state_singleton("workflow_state_projector", factory=WorkflowStateProjector)
def get_workflow_state_projector() -> WorkflowStateProjector:
    """Singleton ``WorkflowStateProjector``."""
