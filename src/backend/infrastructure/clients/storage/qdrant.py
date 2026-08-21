"""Qdrant vector store — production backend (RE_AUDIT_2026-08-25 split).

Wave 6: extracted from vector_store.py (god-object refactor 1/5).
Qdrant is the canonical prod backend — no open CVE per M2 audit.

ABC ``BaseVectorStore`` lives in ``core/interfaces/vector_store.py``.
"""

from __future__ import annotations

import inspect
from typing import Any

from src.backend.core.interfaces.vector_store import BaseVectorStore
from src.backend.core.logging import get_logger
from src.backend.core.resilience.connector_resilience import resilient

__all__ = ("QdrantVectorStore",)

logger = get_logger(__name__)

class QdrantVectorStore(BaseVectorStore):
    """Vector store через Qdrant (default backend)."""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection_name: str = "gd_rag",
        api_key: str | None = None,
        vector_size: int = 384,
    ) -> None:
        self._url = url
        self._collection_name = collection_name
        self._api_key = api_key
        self._vector_size = vector_size
        self._client: Any = None
        self._collection_ready = False

    async def _client_instance(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from qdrant_client import AsyncQdrantClient
        except ImportError as exc:
            raise RuntimeError(
                "qdrant-client не установлен — добавьте в зависимости проекта"
            ) from exc
        self._client = AsyncQdrantClient(url=self._url, api_key=self._api_key)
        return self._client

    async def _ensure_collection(self) -> Any:
        client = await self._client_instance()
        if self._collection_ready:
            return client
        from qdrant_client.http.exceptions import UnexpectedResponse
        from qdrant_client.models import Distance, VectorParams

        try:
            await client.get_collection(self._collection_name)
        except (UnexpectedResponse, ValueError):
            await client.create_collection(
                collection_name=self._collection_name,
                vectors_config=VectorParams(
                    size=self._vector_size, distance=Distance.COSINE
                ),
            )
            logger.info("Qdrant collection '%s' created", self._collection_name)
        self._collection_ready = True
        return client

    @resilient(name="qdrant_upsert", max_attempts=3)
    async def upsert(
        self,
        embeddings: list[list[float]],
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Insert или update vectors в Qdrant collection.

        Args:
            embeddings: list векторов (list[float], размер должен
                совпадать с ``vector_size``).
            documents: list document texts (parallel to embeddings/ids).
            ids: list уникальных ID (parallel).
            metadatas: optional list[dict] с metadata (parallel).

        Note:
            ``client = await self._ensure_collection()`` создаёт
            collection при первом обращении.

        """
        from qdrant_client.models import PointStruct

        client = await self._ensure_collection()
        points = [
            PointStruct(
                id=ids[i],
                vector=embeddings[i],
                payload={
                    "document": documents[i],
                    **(metadatas[i] if metadatas and i < len(metadatas) else {}),
                },
            )
            for i in range(len(ids))
        ]
        await client.upsert(collection_name=self._collection_name, points=points)

    async def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Top-K similarity search в Qdrant.

        Args:
            embedding: query vector.
            top_k: Количество результатов.
            where: optional metadata filter (``{key: value}``).

        Returns:
            list[dict] с полями ``id``, ``document``, ``metadata``,
            ``distance`` (1.0 - similarity).

        """
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = await self._ensure_collection()
        query_filter: Filter | None = None
        if where:
            query_filter = Filter(
                must=[
                    FieldCondition(key=key, match=MatchValue(value=value))
                    for key, value in where.items()
                ]
            )
        results = await client.search(
            collection_name=self._collection_name,
            query_vector=embedding,
            limit=top_k,
            query_filter=query_filter,
        )
        return [
            {
                "id": str(r.id),
                "document": (r.payload or {}).get("document", ""),
                "metadata": {
                    k: v for k, v in (r.payload or {}).items() if k != "document"
                },
                "distance": 1.0 - r.score,
            }
            for r in results
        ]

    async def delete(self, ids: list[str]) -> None:
        """Удалить vectors по list of IDs (atomic batch)."""
        from qdrant_client.models import PointIdsList

        client = await self._ensure_collection()
        await client.delete(
            collection_name=self._collection_name,
            points_selector=PointIdsList(points=list(ids)),
        )

    async def count(self) -> int:
        """Количество vectors в collection (exact count)."""
        client = await self._ensure_collection()
        result = await client.count(collection_name=self._collection_name, exact=True)
        return int(result.count)

    async def delete_where(self, where: dict[str, Any]) -> int:
        """Bulk delete по Qdrant filter (metadata match).

        Args:
            where: ``{key: value}`` filter — Qdrant Filter.

        Returns:
            int count удалённых vectors.

        """
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            FilterSelector,
            MatchValue,
        )

        client = await self._ensure_collection()
        f = Filter(
            must=[
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in where.items()
            ]
        )
        before = (
            await client.count(
                collection_name=self._collection_name, count_filter=f, exact=True
            )
        ).count
        await client.delete(
            collection_name=self._collection_name,
            points_selector=FilterSelector(filter=f),
        )
        return int(before)

    async def count_where(self, where: dict[str, Any]) -> int:
        """Count vectors matching Qdrant filter (metadata match).

        Args:
            where: ``{key: value}`` filter.

        Returns:
            int count.

        """
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = await self._ensure_collection()
        f = Filter(
            must=[
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in where.items()
            ]
        )
        result = await client.count(
            collection_name=self._collection_name, count_filter=f, exact=True
        )
        return int(result.count)

    async def health_check(self, *, mode: str = "fast") -> dict[str, Any]:
        """Health probe для HealthAggregator (Sprint 170 M2 Phase 1)."""
        try:
            import time

            start = time.monotonic()
            ping = getattr(self, "ping", None)
            if ping is None:
                return {"status": "ok", "latency_ms": 0.0, "error": None}
            result = await ping() if inspect.iscoroutinefunction(ping) else ping()
            return {
                "status": "ok" if result else "down",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
                "error": None,
            }
        except Exception as exc:
            return {"status": "down", "error": str(exc)}


