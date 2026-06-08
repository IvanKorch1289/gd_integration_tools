"""L2 Semantic cache (Qdrant cosine similarity).

Использует Qdrant collection для хранения пар (query_embedding → answer).
Поиск — top-1 по cosine; если score >= threshold, возвращается answer.
"""

from __future__ import annotations

import uuid
from typing import Any

import orjson

from src.backend.infrastructure.cache.rag.metrics import record_hit, record_miss
from src.backend.infrastructure.logging.factory import get_logger

logger = get_logger(__name__)

__all__ = ("L2SemanticRagCache",)


class L2SemanticRagCache:
    """Semantic-поиск ответов в Qdrant по эмбеддингам query."""

    def __init__(
        self,
        qdrant_client: Any | None = None,
        embedder: Any | None = None,
        collection: str = "rag_cache_l2",
        threshold: float = 0.92,
        vector_size: int = 1024,
    ) -> None:
        self._client = qdrant_client
        self._embedder = embedder
        self._collection = collection
        self._threshold = threshold
        self._vector_size = vector_size

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from src.backend.infrastructure.clients.storage.vector_store import (
                get_vector_store,
            )

            self._client = get_vector_store()
        except Exception as exc:
            logger.debug("Qdrant client init failed: %s", exc)
            self._client = False
        return self._client

    def _ensure_embedder(self) -> Any:
        if self._embedder is not None:
            return self._embedder
        try:
            from src.backend.services.ai.embedding_providers import (
                get_embedding_provider,
            )

            self._embedder = get_embedding_provider()
        except Exception as exc:
            logger.debug("L2 embedder lazy-init failed: %s", exc)
            self._embedder = False
        return self._embedder

    async def _embed(self, text: str) -> list[float]:
        embedder = self._ensure_embedder()
        if not embedder:
            return []
        try:
            result = await embedder.embed([text])
        except Exception as exc:
            logger.debug("L2 embedder failed: %s", exc)
            return []
        return list(result[0]) if result else []

    async def get(self, query: str, *, tenant: str | None = None) -> Any | None:
        """Возвращает кэшированный answer если score >= threshold."""
        client = self._ensure_client()
        if not client:
            record_miss("l2")
            return None
        vector = await self._embed(query)
        if not vector:
            record_miss("l2")
            return None
        try:
            search = getattr(client, "search", None)
            if search is None:
                record_miss("l2")
                return None
            hits = await search(
                collection=self._collection, vector=vector, limit=1, tenant=tenant
            )
        except Exception as exc:
            logger.debug("L2 search failed: %s", exc)
            record_miss("l2")
            return None
        if not hits:
            record_miss("l2")
            return None
        top = hits[0]
        score = float(top.get("score", 0.0)) if isinstance(top, dict) else 0.0
        if score < self._threshold:
            record_miss("l2")
            return None
        record_hit("l2")
        payload = top.get("payload", {}) if isinstance(top, dict) else {}
        raw = payload.get("answer")
        if isinstance(raw, str):
            try:
                return orjson.loads(raw)
            except Exception as _:
                return raw
        return raw

    async def set(self, query: str, value: Any, *, tenant: str | None = None) -> None:
        client = self._ensure_client()
        if not client:
            return
        vector = await self._embed(query)
        if not vector:
            return
        upsert = getattr(client, "upsert", None)
        if upsert is None:
            return
        payload = {
            "query": query,
            "answer": orjson.dumps(value).decode("utf-8")
            if not isinstance(value, str)
            else value,
        }
        if tenant:
            payload["tenant"] = tenant
        try:
            await upsert(
                collection=self._collection,
                points=[
                    {"id": str(uuid.uuid4()), "vector": vector, "payload": payload}
                ],
            )
        except Exception as exc:
            logger.debug("L2 upsert failed: %s", exc)

    async def flush(self) -> int:
        """Полная очистка коллекции (drop+recreate)."""
        client = self._ensure_client()
        if not client:
            return 0
        recreate = getattr(client, "recreate_collection", None)
        if recreate is None:
            return 0
        try:
            await recreate(collection=self._collection, vector_size=self._vector_size)
            return 1
        except Exception as exc:
            logger.debug("L2 flush failed: %s", exc)
            return 0
