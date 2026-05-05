"""MongoDB-имплементация ``FeedbackRepository`` для AI-feedback (Wave 9.2).

Drop-in замена ``InMemoryFeedbackRepository``: тот же Protocol, тот же
``app_state_singleton`` для получения singleton через ``app.state``.

Коллекция ``ai_feedback``. Документ — это ``AIFeedbackDoc.model_dump(mode="json")``,
``_id == doc.id``. TTL по ``created_at`` (90 дней) — авто-чистка старых записей.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.models.feedback import AIFeedbackDoc, FeedbackLabel
from src.infrastructure.clients.storage.mongodb import MongoDBClient, get_mongo_client

__all__ = ("MongoFeedbackRepository",)

logger = logging.getLogger(__name__)

_COLLECTION = "ai_feedback"
_TTL_SECONDS = 90 * 86400


def _doc_to_model(doc: dict[str, Any]) -> AIFeedbackDoc:
    payload = dict(doc)
    payload["id"] = payload.pop("_id", payload.get("id", ""))
    return AIFeedbackDoc.model_validate(payload)


def _model_to_doc(model: AIFeedbackDoc) -> dict[str, Any]:
    payload = model.model_dump(mode="json")
    payload["_id"] = payload.pop("id")
    return payload


class MongoFeedbackRepository:
    """MongoDB-реализация ``FeedbackRepository``."""

    def __init__(self, client_factory: Any | None = None) -> None:
        self._client_factory = client_factory or get_mongo_client

    def _client(self) -> MongoDBClient:
        return self._client_factory()

    async def ensure_indexes(self) -> None:
        """Создаёт индексы (idempotent)."""
        try:
            collection = self._client().collection(_COLLECTION)
            await collection.create_index(
                [("agent_id", 1), ("feedback", 1)], name="agent_feedback"
            )
            await collection.create_index([("created_at", -1)], name="created_at_desc")
            await collection.create_index(
                [("labeled_at", -1)], name="labeled_at_desc", sparse=True
            )
            await collection.create_index(
                "created_at", name="ttl_created_at", expireAfterSeconds=_TTL_SECONDS
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MongoFeedbackRepository: ensure_indexes failed: %s", exc)

    async def save(self, doc: AIFeedbackDoc) -> AIFeedbackDoc:
        await self._client().insert_one(_COLLECTION, _model_to_doc(doc))
        return doc

    async def get(self, doc_id: str) -> AIFeedbackDoc | None:
        raw = await self._client().find_one(_COLLECTION, {"_id": doc_id})
        return _doc_to_model(raw) if raw else None

    async def update(self, doc: AIFeedbackDoc) -> AIFeedbackDoc:
        payload = _model_to_doc(doc)
        modified = await self._client().update_one(
            _COLLECTION, query={"_id": doc.id}, update=payload, upsert=False
        )
        if modified == 0:
            existing = await self._client().find_one(_COLLECTION, {"_id": doc.id})
            if existing is None:
                raise KeyError(f"AIFeedbackDoc {doc.id!r} не найден")
        return doc

    async def list_pending(
        self, *, agent_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[AIFeedbackDoc]:
        query: dict[str, Any] = {"feedback": None}
        if agent_id is not None:
            query["agent_id"] = agent_id
        docs = await self._client().find(
            _COLLECTION,
            query=query,
            limit=limit,
            skip=offset,
            sort=[("created_at", -1)],
        )
        return [_doc_to_model(d) for d in docs]

    async def list_labeled(
        self,
        *,
        label: FeedbackLabel | None = None,
        agent_id: str | None = None,
        indexed_in_rag: bool | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AIFeedbackDoc]:
        query: dict[str, Any] = {"feedback": {"$ne": None}}
        if label is not None:
            query["feedback"] = label
        if agent_id is not None:
            query["agent_id"] = agent_id
        if indexed_in_rag is not None:
            query["indexed_in_rag"] = indexed_in_rag
        docs = await self._client().find(
            _COLLECTION,
            query=query,
            limit=limit,
            skip=offset,
            sort=[("labeled_at", -1)],
        )
        return [_doc_to_model(d) for d in docs]

    async def stats(self) -> dict[str, int]:
        client = self._client()
        result = {"pending": 0, "positive": 0, "negative": 0, "skip": 0, "indexed": 0}
        result["pending"] = await client.count(_COLLECTION, {"feedback": None})
        for label in ("positive", "negative", "skip"):
            result[label] = await client.count(_COLLECTION, {"feedback": label})
        result["indexed"] = await client.count(_COLLECTION, {"indexed_in_rag": True})
        return result
