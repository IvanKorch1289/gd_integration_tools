"""Stream E.7: semantic-память LangMem поверх Qdrant.

Semantic = плотные векторы поверх произвольных фактов. Embedder
поднимает текст в вектор; backend-Qdrant хранит ``point_id``,
``vector``, ``payload``.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.backend.infrastructure.logging.factory import get_logger

logger = get_logger(__name__)

__all__ = ("SemanticMemory",)


class SemanticMemory:
    """Векторная (semantic) память поверх Qdrant.

    Args:
        qdrant_client: Async Qdrant клиент с методом ``upsert(collection,
            points=[...])``. ``None`` → :meth:`add` поднимает RuntimeError.
        embedder: Источник эмбеддингов с методом ``embed(texts)``.
        collection: Имя коллекции в Qdrant (default ``langmem_semantic``).
    """

    def __init__(
        self,
        qdrant_client: Any | None = None,
        embedder: Any | None = None,
        collection: str = "langmem_semantic",
    ) -> None:
        self._client = qdrant_client
        self._embedder = embedder
        self._collection = collection

    @property
    def is_configured(self) -> bool:
        return self._client is not None and self._embedder is not None

    async def add(
        self,
        *,
        text: str,
        tenant: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> str:
        """Embed → upsert в Qdrant. Возвращает point_id (uuid4)."""
        if not self.is_configured:
            raise RuntimeError(
                "SemanticMemory: embedder или qdrant_client не сконфигурированы."
            )
        vectors = await self._embedder.embed([text])
        point_id = str(uuid.uuid4())
        payload: dict[str, Any] = {"text": text, **(meta or {})}
        if tenant:
            payload["tenant"] = tenant
        upsert = getattr(self._client, "upsert", None)
        if upsert is not None:
            await upsert(
                collection=self._collection,
                points=[{"id": point_id, "vector": vectors[0], "payload": payload}],
            )
        return point_id
