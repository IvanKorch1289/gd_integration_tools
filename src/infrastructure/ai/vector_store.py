"""Qdrant-based vector store (D3, ADR-014).

Заменяет chromadb (sync, менее зрелый). Async, HTTP/gRPC-агностичен
(используем HTTP через httpx/qdrant-client), integrates с semantic
cache и RAG pipeline.

Scaffold-уровень: публичный интерфейс, конкретная реализация
подтягивается через qdrant-client.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

__all__ = ("QdrantVectorStore",)

logger = logging.getLogger("ai.vector_store")


@dataclass(slots=True)
class QdrantVectorStore:
    """Tiny client wrapper."""

    url: str = "http://localhost:6333"
    collection: str = "gdi"
    api_key: str | None = None

    def _client(self):
        try:
            from qdrant_client import AsyncQdrantClient  # type: ignore[import-not-found]

            return AsyncQdrantClient(url=self.url, api_key=self.api_key)
        except ImportError:
            raise RuntimeError("qdrant-client не установлен — установите gdi[ai]")

    async def upsert(self, points: list[dict[str, Any]]) -> None:
        from qdrant_client.models import PointStruct  # type: ignore[import-not-found]

        client = self._client()
        await client.upsert(
            collection_name=self.collection,
            points=[PointStruct(id=p["id"], vector=p["vector"], payload=p.get("payload", {})) for p in points],
        )

    async def search(self, vector: list[float], *, limit: int = 10) -> list[dict[str, Any]]:
        client = self._client()
        result = await client.search(collection_name=self.collection, query_vector=vector, limit=limit)
        return [{"id": r.id, "score": r.score, "payload": r.payload} for r in result]
