"""L1 Exact KV cache (Redis prefix ``rag:l1:``)."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import orjson

from src.backend.infrastructure.cache.rag.metrics import record_hit, record_miss

logger = logging.getLogger(__name__)

__all__ = ("L1ExactCache",)


class L1ExactCache:
    """Exact-key KV-кэш ответов RAG в Redis."""

    PREFIX = "rag:l1:"

    def __init__(
        self,
        redis_client: Any | None = None,
        ttl_seconds: int = 3600,
        prefix: str | None = None,
    ) -> None:
        self._client = redis_client
        self._ttl = ttl_seconds
        self._prefix = prefix or self.PREFIX

    def _key(self, query: str, *, tenant: str | None = None) -> str:
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
        if tenant:
            return f"{self._prefix}{tenant}:{digest}"
        return f"{self._prefix}{digest}"

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        from src.backend.infrastructure.clients.storage.redis import get_redis_client

        self._client = get_redis_client()
        return self._client

    async def get(self, query: str, *, tenant: str | None = None) -> Any | None:
        """Возвращает кэшированный ответ либо ``None``."""
        client = self._ensure_client()
        try:
            raw = await client.cache_get(self._key(query, tenant=tenant))
        except Exception as exc:
            logger.debug("L1 cache get failed: %s", exc)
            record_miss("l1")
            return None
        if not raw:
            record_miss("l1")
            return None
        record_hit("l1")
        try:
            return orjson.loads(raw)
        except Exception as exc:
            logger.debug("L1 cache decode failed: %s", exc)
            return None

    async def set(self, query: str, value: Any, *, tenant: str | None = None) -> None:
        client = self._ensure_client()
        try:
            await client.cache_set(
                self._key(query, tenant=tenant), orjson.dumps(value), self._ttl
            )
        except Exception as exc:
            logger.debug("L1 cache set failed: %s", exc)

    async def invalidate(self, query: str, *, tenant: str | None = None) -> None:
        client = self._ensure_client()
        try:
            await client.cache_delete(self._key(query, tenant=tenant))
        except Exception as exc:
            logger.debug("L1 cache invalidate failed: %s", exc)

    async def flush(self) -> int:
        """Сбрасывает все ключи tier'а. Возвращает кол-во удалённых."""
        client = self._ensure_client()
        try:

            async def _scan_and_unlink(conn: Any) -> int:
                deleted = 0
                async for key in conn.scan_iter(match=f"{self._prefix}*", count=200):
                    await conn.unlink(key)
                    deleted += 1
                return deleted

            return int(await client.execute("cache", _scan_and_unlink))
        except Exception as exc:
            logger.debug("L1 cache flush failed: %s", exc)
            return 0
