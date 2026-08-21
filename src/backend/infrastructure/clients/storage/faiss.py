"""FAISS in-memory vector store (RE_AUDIT_2026-08-25 split).

Wave 6: extracted from vector_store.py (god-object refactor 1/5).
In-memory FAISS — for dev/tests, no external dependencies.
Production should use QdrantVectorStore.

ABC ``BaseVectorStore`` lives in ``core/interfaces/vector_store.py``.
"""

from __future__ import annotations

import inspect
from typing import Any

from src.backend.core.interfaces.vector_store import BaseVectorStore
from src.backend.core.resilience.connector_resilience import resilient

__all__ = ("FAISSVectorStore",)

class FAISSVectorStore(BaseVectorStore):
    """In-memory FAISS vector store (для разработки и тестов)."""

    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension
        self._index: Any = None
        self._id_map: dict[str, int] = {}
        self._docs: dict[str, str] = {}
        self._metas: dict[str, dict[str, Any]] = {}
        self._next_idx = 0

    def _ensure_index(self) -> Any:
        if self._index is not None:
            return self._index
        import faiss

        self._index = faiss.IndexFlatL2(self._dimension)
        return self._index

    @resilient(name="qdrant_upsert", max_attempts=3)
    async def upsert(
        self,
        embeddings: list[list[float]],
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Insert or update vectors + documents + metadata."""
        import numpy as np

        index = self._ensure_index()
        vectors = np.array(embeddings, dtype="float32")
        index.add(vectors)

        for i, doc_id in enumerate(ids):
            self._id_map[doc_id] = self._next_idx + i
            self._docs[doc_id] = documents[i]
            if metadatas:
                self._metas[doc_id] = metadatas[i]
        self._next_idx += len(ids)

    async def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Ищет ближайшие векторы через FAISS и возвращает top-k документов с метаданными."""
        import numpy as np

        index = self._ensure_index()
        if index.ntotal == 0:
            return []

        query_vec = np.array([embedding], dtype="float32")
        distances, indices = index.search(query_vec, min(top_k, index.ntotal))

        idx_to_id = {v: k for k, v in self._id_map.items()}
        results = []
        for i, idx in enumerate(indices[0]):
            if idx < 0:
                continue
            doc_id = idx_to_id.get(int(idx), "")
            results.append(
                {
                    "id": doc_id,
                    "document": self._docs.get(doc_id, ""),
                    "metadata": self._metas.get(doc_id, {}),
                    "distance": float(distances[0][i]),
                }
            )
        return results

    async def delete(self, ids: list[str]) -> None:
        """Delete vectors по списку ``ids``."""
        for doc_id in ids:
            self._id_map.pop(doc_id, None)
            self._docs.pop(doc_id, None)
            self._metas.pop(doc_id, None)

    async def count(self) -> int:
        """Общее количество vectors в collection."""
        return len(self._docs)

    async def delete_where(self, where: dict[str, Any]) -> int:
        """Delete vectors matching ``where`` filter; вернуть count удалённых."""
        to_remove = [
            doc_id
            for doc_id, meta in self._metas.items()
            if all(meta.get(k) == v for k, v in where.items())
        ]
        for doc_id in to_remove:
            self._id_map.pop(doc_id, None)
            self._docs.pop(doc_id, None)
            self._metas.pop(doc_id, None)
        return len(to_remove)

    async def count_where(self, where: dict[str, Any]) -> int:
        """Count vectors matching ``where`` filter."""
        return sum(
            1
            for meta in self._metas.values()
            if all(meta.get(k) == v for k, v in where.items())
        )

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


