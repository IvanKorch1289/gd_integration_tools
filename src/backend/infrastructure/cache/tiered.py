"""Tiered cache backend: L1 in-process + L2 remote (S168 W10 P1-9).

Wraps a local L1 (typically :class:`MemoryBackend`) and a remote
L2 (typically :class:`RedisBackend`). Read-through pattern:
1. Check L1 → if hit, return.
2. Check L2 → if hit, populate L1, return.
3. Miss → caller computes, set() propagates to both L1 and L2.

This is the canonical RAG 3-tier pattern (L1 in-process + L2 Redis)
scaled down to 2-tier for the ``memory`` cache backend default.

L3 (disk / RAG tier) is configured separately in
:infrastructure.cache.rag.* — not affected by this module.
"""

from __future__ import annotations

import asyncio

from src.backend.core.interfaces.cache import CacheBackend
from src.backend.core.logging import get_logger

__all__ = ("TieredCacheBackend",)

logger = get_logger("infrastructure.cache.tiered")


class TieredCacheBackend(CacheBackend):
    """L1 + L2 cache (S168 W10 P1-9, per Task 22 master prompt).

    Args:
        l1: local CacheBackend (e.g. MemoryBackend).
        l2: remote CacheBackend (e.g. RedisBackend).
        promote_ttl: TTL при promote из L2 в L1 (default 60s).
    """

    def __init__(
        self, l1: CacheBackend, l2: CacheBackend, promote_ttl: int = 60
    ) -> None:
        self._l1 = l1
        self._l2 = l2
        self._promote_ttl = promote_ttl
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> bytes | None:
        """Get value from tiered cache (L1 → L2 with promotion.

        Args:
            key: Cache key.

        Returns:
            Cached bytes or None if not found.
        """
        # L1 first
        val = await self._l1.get(key)
        if val is not None:
            return val
        # L2 fallback
        val = await self._l2.get(key)
        if val is not None:
            # Promote to L1 (best-effort; L1 may have per-key TTL ignored)
            try:
                await self._l1.set(key, val, ttl=self._promote_ttl)
            except Exception as exc:  # pragma: no cover
                logger.debug("TieredCache: L1 promote failed: %s", exc)
            return val
        return None

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set value in both cache tiers.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Optional TTL in seconds.
        """
        # Set both (L1 best-effort)
        try:
            await self._l1.set(key, value, ttl=ttl)
        except Exception as exc:  # pragma: no cover
            logger.debug("TieredCache: L1 set failed: %s", exc)
        # L2 authoritative
        await self._l2.set(key, value, ttl=ttl)

    async def delete(self, *keys: str) -> None:
        """Delete values from both cache tiers.

        Args:
            keys: Cache keys to delete.
        """
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._l1.delete(*keys))
            tg.create_task(self._l2.delete(*keys))

    async def delete_pattern(self, pattern: str) -> None:
        """Delete values matching pattern from both tiers.

        Args:
            pattern: Glob pattern to match keys.
        """
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._l1.delete_pattern(pattern))
            tg.create_task(self._l2.delete_pattern(pattern))

    async def exists(self, key: str) -> bool:
        """Check if key exists in either cache tier.

        Args:
            key: Cache key.

        Returns:
            True if key exists in L1 or L2, False otherwise.
        """
        return await self._l1.exists(key) or await self._l2.exists(key)
