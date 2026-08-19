"""In-process LRU cache for embedding vectors (Sprint 86).

ponytail: async-native rewrite — threading.Lock blocked event loop when called
from async context (L2SemanticRagCache._embed is async). Fixed by replacing
with asyncio.Lock and making get/set async.

cycle-1/P3-01 fix: custom TTL+LRU заменён на `cachetools.TTLCache` wrapped
в `asyncio.Lock` (cachetools не thread-safe). Async API сохранён.
"""

from __future__ import annotations

import asyncio
import hashlib

from cachetools import TTLCache

__all__ = ("EmbeddingVectorCache",)


class EmbeddingVectorCache:
    """Async-safe in-process cache for query → embedding vector with TTL.

    Внутренне использует ``cachetools.TTLCache`` (не thread-safe по дизайну),
    обёрнутый в ``asyncio.Lock`` для async-контекста.
    """

    def __init__(self, ttl_seconds: float = 300.0, maxsize: int = 1024) -> None:
        self._ttl = ttl_seconds
        self._maxsize = maxsize
        self._store: TTLCache[str, list[float]] = TTLCache(
            maxsize=maxsize, ttl=ttl_seconds
        )
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()

    async def get(self, query: str) -> list[float] | None:
        """Get cached embedding vector for query (async-safe)."""
        key = self._key(query)
        async with self._lock:
            try:
                return list(self._store[key])
            except KeyError:
                return None

    async def set(self, query: str, vector: list[float]) -> None:
        """Cache embedding vector for query (async-safe)."""
        key = self._key(query)
        async with self._lock:
            self._store[key] = list(vector)
