"""In-process LRU cache for embedding vectors (Sprint 86).

 ponytail: async-native rewrite — threading.Lock blocked event loop when called
 from async context (L2SemanticRagCache._embed is async). Fixed by replacing
 with asyncio.Lock and making get/set async.
"""

from __future__ import annotations

import asyncio
import hashlib
import time

__all__ = ("EmbeddingVectorCache",)


class EmbeddingVectorCache:
    """Async-safe in-process cache for query → embedding vector with TTL."""

    def __init__(self, ttl_seconds: float = 300.0, maxsize: int = 1024) -> None:
        self._ttl = ttl_seconds
        self._maxsize = maxsize
        self._store: dict[str, tuple[list[float], float]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()

    async def get(self, query: str) -> list[float] | None:
        """Get cached embedding vector for query (async-safe).

        Args:
            query: Query string.

        Returns:
            Cached embedding vector or None if not found/expired.
        """
        key = self._key(query)
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            vector, expires = entry
            if time.monotonic() > expires:
                del self._store[key]
                return None
            return list(vector)

    async def set(self, query: str, vector: list[float]) -> None:
        """Cache embedding vector for query (async-safe).

        Args:
            query: Query string.
            vector: Embedding vector to cache.
        """
        key = self._key(query)
        async with self._lock:
            while len(self._store) >= self._maxsize:
                try:
                    self._store.pop(next(iter(self._store)))
                except StopIteration:
                    break
            self._store[key] = (list(vector), time.monotonic() + self._ttl)
