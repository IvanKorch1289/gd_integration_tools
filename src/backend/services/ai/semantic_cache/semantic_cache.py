"""S67 W3 - semantic_cache.py part of semantic_cache decomp.

Per-class file split.

Classes: SemanticCache.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

#: Redis pub/sub канал для cross-instance invalidation L3-кеша.
RAG_CACHE_INVALIDATE_CHANNEL = "rag-cache-invalidate"


class SemanticCache:
    """Cache LLM responses by semantic similarity of queries.

    Usage::
        cache = get_semantic_cache()
        hit = await cache.lookup(query, provider="claude")
        if hit:
            return hit["response"]

        response = await llm.chat(query)
        await cache.store(query, response, provider="claude")
    """

    def __init__(
        self,
        *,
        similarity_threshold: float = 0.95,
        ttl_seconds: int = 3600,
        namespace: str = "llm_semantic_cache",
    ) -> None:
        self._threshold = similarity_threshold
        self._ttl = ttl_seconds
        self._namespace = namespace

    async def lookup(
        self, query: str, *, provider: str | None = None, model: str | None = None
    ) -> dict[str, Any] | None:
        """Ищет кешированный response по semantic similarity.

        Returns {response, similarity, cached_at, source} или None.
        """
        # Try exact hash match first (fast path)
        exact = await self._exact_lookup(query, provider, model)
        if exact is not None:
            return {**exact, "source": "exact", "similarity": 1.0}

        # Semantic search в vector store
        return await self._semantic_lookup(query, provider, model)

    async def store(
        self,
        query: str,
        response: Any,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        """Сохраняет (query, response) с embedding."""
        await self._exact_store(query, response, provider, model)
        await self._semantic_store(query, response, provider, model)

    def _hash_key(self, query: str, provider: str | None, model: str | None) -> str:
        raw = f"{provider or ''}:{model or ''}:{query}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def _exact_lookup(
        self, query: str, provider: str | None, model: str | None
    ) -> dict[str, Any] | None:
        """Redis-backed exact lookup (fast path)."""
        # Wave 6.3: Redis-клиент — через core/di.providers.
        try:
            import orjson

            from src.backend.core.di.providers import get_redis_stream_client_provider

            redis_client = get_redis_stream_client_provider()
        except ImportError:
            return None

        key = f"{self._namespace}:exact:{self._hash_key(query, provider, model)}"
        try:
            raw = getattr(redis_client, "_raw_client", None) or redis_client
            data = await raw.get(key)
            if data is None:
                return None
            return orjson.loads(data)
        except Exception as _:
            return None

    async def _exact_store(
        self, query: str, response: Any, provider: str | None, model: str | None
    ) -> None:
        # Wave 6.3: Redis-клиент — через core/di.providers.
        try:
            import orjson

            from src.backend.core.di.providers import get_redis_stream_client_provider

            redis_client = get_redis_stream_client_provider()
        except ImportError:
            return

        key = f"{self._namespace}:exact:{self._hash_key(query, provider, model)}"
        payload = orjson.dumps(
            {
                "query": query,
                "response": response,
                "provider": provider,
                "model": model,
                "cached_at": time.time(),
            }
        )
        try:
            raw = getattr(redis_client, "_raw_client", None) or redis_client
            await raw.set(key, payload, ex=self._ttl)
        except Exception as exc:
            logger.debug("Semantic cache exact store failed: %s", exc)

    async def _semantic_lookup(
        self, query: str, provider: str | None, model: str | None
    ) -> dict[str, Any] | None:
        """Vector similarity поиск через RAG service."""
        try:
            from src.backend.services.ai.rag_service import get_rag_service

            rag = get_rag_service()
        except ImportError:
            return None

        try:
            results = await rag.search(query=query, top_k=1, namespace=self._namespace)
        except Exception as exc:
            logger.debug("Semantic cache search failed: %s", exc)
            return None

        if not results:
            return None

        top = results[0]
        similarity = float(top.get("score", 0.0) if isinstance(top, dict) else 0.0)
        if similarity < self._threshold:
            return None

        meta = top.get("metadata", {}) if isinstance(top, dict) else {}
        return {
            "response": meta.get("response"),
            "cached_at": meta.get("cached_at"),
            "source": "semantic",
            "similarity": similarity,
        }

    async def _semantic_store(
        self, query: str, response: Any, provider: str | None, model: str | None
    ) -> None:
        """Сохраняет query + response в vector store для semantic search."""
        try:
            from src.backend.services.ai.rag_service import get_rag_service

            rag = get_rag_service()
        except ImportError:
            return

        # IL-CRIT1.3: `RAGService.ingest()` ожидает `content: str` +
        # `metadata: dict` + `namespace: str` (не `documents: list` +
        # `metadata: list`). Ранее параметры были переданы неверно —
        # ингест молча падал в `except Exception`, semantic-lookup не
        # наполнялся.
        try:
            if hasattr(rag, "ingest"):
                # Round 7 Sprint 1.1 P0 fix: mask PII в query перед
                # сохранением в vector store — чтобы запросы с персональными
                # данными не оседали в vector store навсегда. Future queries
                # тоже маскируются при lookup (round-trip consistency).
                try:
                    from src.backend.services.ai.rag_ingest_service import (
                        _maybe_mask_pii,
                    )

                    masked_query, pii_meta = _maybe_mask_pii(query)
                except (ImportError, RuntimeError, ValueError) as pii_mask_exc:
                    # D-A1-04 fix (cycle 40): narrow exceptions + observability.
                    # Bare `except Exception` маскировал ImportError (rag_ingest_service
                    # недоступен), RuntimeError/ValueError (sanitizer failure).
                    # Fallback: ingest raw query (raw + pii_masked=False flag).
                    from src.backend.core.logging import get_logger

                    get_logger(__name__).warning(
                        "semantic_cache.pii_mask_failed",
                        extra={"error": str(pii_mask_exc)},
                    )
                    masked_query, pii_meta = query, {"pii_masked": False}
                await rag.ingest(
                    content=masked_query,
                    metadata={
                        "response": response,
                        "provider": provider,
                        "model": model,
                        "cached_at": time.time(),
                        **pii_meta,
                    },
                    namespace=self._namespace,
                )
        except Exception as exc:
            logger.debug("Semantic cache store failed: %s", exc)
