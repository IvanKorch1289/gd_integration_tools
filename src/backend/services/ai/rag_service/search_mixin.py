from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.backend.core.di import app_state_singleton
from src.backend.core.interfaces.vector_store import BaseVectorStore
from src.backend.core.logging import get_logger
from src.backend.services.ai.embedding_providers import (
    EmbeddingProvider,
    get_embedding_provider,
)
from src.backend.services.ai.rag_augment import (
    AugmentResult,
    FreshnessLabel,
    build_augment_result,
)

if TYPE_CHECKING:  # pragma: no cover
    from src.backend.infrastructure.cache.rag.three_tier import ThreeTierRagCache

class SearchMixin:
    """search (semantic search with cache) для RAGService. S64 W4 extraction."""

    __slots__ = ()

    async def search(
        self, query: str, top_k: int = 5, namespace: str | None = None
    ) -> list[dict[str, Any]]:
        """Семантический поиск с использованием L3 retrieval-tier."""
        if self._cache is not None:
            chunks, tier = await self._cache.lookup_chunks(query, namespace=namespace)
            if chunks is not None:
                logger.debug(
                    "RAG retrieval hit on tier %s (namespace=%s)", tier, namespace
                )
                return chunks

        embedding = (await self._embed([query]))[0]

        where = None
        if namespace:
            where = {"namespace": namespace}

        results = await self._store.query(embedding=embedding, top_k=top_k, where=where)
        results = _filter_by_embedding_version(results)

        if self._cache is not None and results:
            try:
                await self._cache.store_chunks(query, results, namespace=namespace)
            except Exception as exc:
                logger.debug("RAG L3 store skipped: %s", exc)
        return results

