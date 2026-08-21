"""Chroma vector store — gated by CVE protection (RE_AUDIT_2026-08-25 split).

Wave 6: extracted from vector_store.py (god-object refactor 1/5).
ChromaDB has a pre-auth code injection CVE (no upstream fix as of
2026-07-27) — gated by env override ``CHROMADB_ALLOW_CVE=true``
in production profiles. For prod RAG prefer Qdrant.

ABC ``BaseVectorStore`` lives in ``core/interfaces/vector_store.py``.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from typing import Any

from src.backend.core.config.profile import AppProfileChoices, get_active_profile
from src.backend.core.interfaces.vector_store import BaseVectorStore
from src.backend.core.logging import get_logger
from src.backend.core.resilience.connector_resilience import resilient

__all__ = ("ChromaVectorStore",)

logger = get_logger(__name__)

class ChromaVectorStore(BaseVectorStore):
    """Vector store через Chroma DB."""

    def __init__(
        self, host: str = "localhost", port: int = 8000, collection_name: str = "gd_rag"
    ) -> None:
        self._host = host
        self._port = port
        self._collection_name = collection_name
        self._client: Any = None
        self._collection: Any = None

    async def _ensure_collection(self) -> Any:
        if self._collection is not None:
            return self._collection

        # M2: chromadb<=1.5.9 has a pre-auth code injection CVE
        # (pyproject.toml comment). Refuse to instantiate in prod/staging
        # unless the operator has explicitly opted in via env override
        # ``CHROMADB_ALLOW_CVE=true``. dev_light/dev profiles keep the
        # legacy behavior with a loud warning.
        active = get_active_profile()
        is_prod_like = active in {AppProfileChoices.prod, AppProfileChoices.staging}
        if is_prod_like:
            import os  # local import: hot-path avoidance (only when CVE gate triggered)

            allow_cve = os.environ.get("CHROMADB_ALLOW_CVE", "").lower() in {
                "1",
                "true",
                "yes",
            }
            if not allow_cve:
                raise RuntimeError(
                    "ChromaVectorStore is disabled in profile "
                    f"{active.value!r} due to chromadb<=1.5.9 CVE "
                    "(pre-auth code injection). Use QdrantVectorStore "
                    "or set CHROMADB_ALLOW_CVE=true to override. "
                    "See pyproject.toml comment for CVE id."
                )
        logger.warning(
            "ChromaVectorStore used in profile %s — known CVE in "
            "chromadb<=1.5.9 (pre-auth code injection). Prefer "
            "QdrantVectorStore in production.",
            active.value,
        )

        chromadb = importlib.import_module("chromadb")

        self._client = await asyncio.to_thread(
            chromadb.HttpClient, host=self._host, port=self._port
        )
        self._collection = await asyncio.to_thread(
            self._client.get_or_create_collection, self._collection_name
        )
        logger.info("Chroma collection '%s' ready", self._collection_name)
        return self._collection

    @resilient(name="qdrant_upsert", max_attempts=3)
    async def upsert(
        self,
        embeddings: list[list[float]],
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Insert или update vectors в Chroma collection (async via to_thread)."""
        collection = await self._ensure_collection()
        kwargs: dict[str, Any] = {
            "ids": ids,
            "embeddings": embeddings,
            "documents": documents,
        }
        if metadatas:
            kwargs["metadatas"] = metadatas
        await asyncio.to_thread(collection.upsert, **kwargs)

    async def query(
        self,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Top-K similarity search в Chroma.

        Returns:
            list[dict] с ``id``, ``document``, ``metadata``, ``distance``.

        """
        collection = await self._ensure_collection()
        kwargs: dict[str, Any] = {
            "query_embeddings": [embedding],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        results = await asyncio.to_thread(collection.query, **kwargs)

        items = []
        for i, doc_id in enumerate(results["ids"][0]):
            items.append(
                {
                    "id": doc_id,
                    "document": results["documents"][0][i]
                    if results["documents"]
                    else "",
                    "metadata": results["metadatas"][0][i]
                    if results["metadatas"]
                    else {},
                    "distance": results["distances"][0][i]
                    if results["distances"]
                    else 0.0,
                }
            )
        return items

    async def delete(self, ids: list[str]) -> None:
        """Удалить vectors по list of IDs (async via to_thread)."""
        collection = await self._ensure_collection()
        await asyncio.to_thread(collection.delete, ids=ids)

    async def count(self) -> int:
        """Количество vectors в Chroma collection."""
        collection = await self._ensure_collection()
        return await asyncio.to_thread(collection.count)

    async def delete_where(self, where: dict[str, Any]) -> int:
        """Bulk delete по metadata filter.

        Args:
            where: Chroma where filter (``{key: value}``).

        Returns:
            int count удалённых vectors (``before - after``).

        """
        collection = await self._ensure_collection()
        before = await asyncio.to_thread(collection.count)
        await asyncio.to_thread(collection.delete, where=where)
        after = await asyncio.to_thread(collection.count)
        return int(before - after)

    async def count_where(self, where: dict[str, Any]) -> int:
        """Count vectors matching metadata filter.

        Args:
            where: Chroma where filter.

        Returns:
            int count (через ``collection.get(where=...)``).

        """
        collection = await self._ensure_collection()
        result = await asyncio.to_thread(collection.get, where=where, include=[])
        ids = (
            result.get("ids")
            if isinstance(result, dict)
            else getattr(result, "ids", [])
        )
        return len(ids) if ids else 0

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


