"""MongoDB-имплементация ``ExpressSessionStore`` (Wave 9.2.4).

Коллекция ``express_sessions``. TTL по ``last_activity_at``
(1 час неактивности → авто-удаление).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from src.backend.core.di import app_state_singleton
from src.backend.core.logging import get_logger
from src.backend.core.models.express import ExpressSession
from src.backend.infrastructure.clients.storage.mongodb import (
    MongoDBClient,
    get_mongo_client,
)

__all__ = ("MongoExpressSessionStore", "get_express_session_store")

logger = get_logger(__name__)

_COLLECTION = "express_sessions"
_TTL_SECONDS = 3600


def _utc_now() -> datetime:
    """Метод _utc_now (см. signature)."""
    return datetime.now(UTC)


def _doc_to_session(doc: dict[str, Any]) -> ExpressSession:
    """Метод _doc_to_session (см. signature)."""
    payload = dict(doc)
    payload.pop("_id", None)
    return ExpressSession.model_validate(payload)


class MongoExpressSessionStore:
    """Mongo-реализация ``ExpressSessionStore``."""

    def __init__(self, client_factory: Any | None = None) -> None:
        """Метод __init__ (см. signature)."""
        self._client_factory = client_factory or get_mongo_client

    def _client(self) -> MongoDBClient:
        """Метод _client (см. signature)."""
        return self._client_factory()

    async def ensure_indexes(self) -> None:
        """Метод ensure_indexes (см. signature)."""
        try:
            collection = self._client().collection(_COLLECTION)
            await collection.create_index(
                "last_activity_at",
                name="ttl_last_activity",
                expireAfterSeconds=_TTL_SECONDS,
            )
        except Exception as exc:
            logger.warning("MongoExpressSessionStore: ensure_indexes failed: %s", exc)

    async def create(
        self, bot_id: str, *, initial_context: dict[str, Any] | None = None,
    ) -> str:
        """Метод create (см. signature)."""
        session_id = uuid4().hex
        now = _utc_now()
        await self._client().insert_one(
            _COLLECTION,
            {
                "_id": session_id,
                "session_id": session_id,
                "bot_id": bot_id,
                "context": dict(initial_context or {}),
                "state": "active",
                "created_at": now.isoformat(),
                "last_activity_at": now,
            },
        )
        return session_id

    async def get(self, session_id: str) -> ExpressSession | None:
        """Метод get (см. signature)."""
        doc = await self._client().find_one(_COLLECTION, {"_id": session_id})
        return _doc_to_session(doc) if doc else None

    async def update_context(
        self, session_id: str, context_delta: dict[str, Any],
    ) -> None:
        """Метод update_context (см. signature)."""
        if not context_delta:
            return
        update = {f"context.{k}": v for k, v in context_delta.items()}
        update["last_activity_at"] = _utc_now()
        await self._client().update_one(
            _COLLECTION, query={"_id": session_id}, update=update, upsert=True,
        )

    async def ping(self, session_id: str) -> None:
        """Метод ping (см. signature)."""
        await self._client().update_one(
            _COLLECTION,
            query={"_id": session_id},
            update={"last_activity_at": _utc_now()},
            upsert=False,
        )


@app_state_singleton("express_session_store", factory=MongoExpressSessionStore)
def get_express_session_store() -> MongoExpressSessionStore:  # type: ignore[empty-body]
    """Singleton ``MongoExpressSessionStore``."""
