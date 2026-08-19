"""L3 Retrieval cache (Redis prefix ``rag:l3:v2:``).

Sprint 2.1 (L5 RAG/Memory tenant-scope): добавлен tenant-prefix к ключу
для закрытия cross-tenant cache poisoning в L3 (L1/L2 уже tenant-aware).
Consistent с :class:`TenantCacheBackend` ``tenant:{id}:` / `_unscoped_`
sentinel. Версионированный namespace (``v2``) обеспечивает backward-compat:
старые ключи ``rag:l3:*`` остаются в Redis, но больше не достижимы
(новые ключи — под ``rag:l3:v2:*``); collision невозможен.
"""

from __future__ import annotations

import hashlib
from typing import Any

import orjson

from src.backend.core.logging import get_logger
from src.backend.infrastructure.cache.rag.metrics import record_hit, record_miss

logger = get_logger(__name__)

__all__ = ("L3RetrievalCache",)

# Sentinel-значения для tenant/namespace при отсутствии явного scope.
# Выделены в module-level константы чтобы избежать magic-strings
# в hot-path и упростить grep по tenant-isolation тестам.
_UNSCOPED_TENANT = "_unscoped_"
_GLOBAL_NAMESPACE = "_global_"


class L3RetrievalCache:
    """KV-кэш сырых retrieval-чанков (без LLM-ответа)."""

    PREFIX = "rag:l3:v2:"

    def __init__(
        self,
        redis_client: Any | None = None,
        ttl_seconds: int = 600,
        prefix: str | None = None,
    ) -> None:
        self._client = redis_client
        self._ttl = ttl_seconds
        self._prefix = prefix or self.PREFIX

    def _key(
        self, query: str, *, tenant: str | None = None, namespace: str | None = None
    ) -> str:
        """Строит tenant-aware ключ: ``{prefix}tenant:{t}:{ns}:{digest}``.

        Args:
            query: Текст запроса (хэшируется).
            tenant: Tenant scope (``None`` → sentinel ``_unscoped_``).
            namespace: Namespace scope (``None`` → sentinel ``_global_``).

        Returns:
            Полный Redis-ключ с sha256-digest.

        """
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
        tenant_part = tenant or _UNSCOPED_TENANT
        namespace_part = namespace or _GLOBAL_NAMESPACE
        return f"{self._prefix}tenant:{tenant_part}:{namespace_part}:{digest}"

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        from src.backend.infrastructure.clients.storage.redis import get_redis_client

        self._client = get_redis_client()
        return self._client

    async def get(
        self, query: str, *, tenant: str | None = None, namespace: str | None = None
    ) -> list[dict[str, Any]] | None:
        """Get cached retrieval results.

        Args:
            query: Query string.
            tenant: Optional tenant scope (Sprint 2.1).
            namespace: Optional namespace scope.

        Returns:
            List of cached chunks or None if not found.

        """
        client = self._ensure_client()
        try:
            raw = await client.cache_get(
                self._key(query, tenant=tenant, namespace=namespace)
            )
        except Exception as exc:
            logger.debug("L3 cache get failed: %s", exc)
            record_miss("l3")
            return None
        if not raw:
            record_miss("l3")
            return None
        record_hit("l3")
        try:
            data = orjson.loads(raw)
            return data if isinstance(data, list) else None
        except Exception as exc:
            logger.debug("L3 cache decode failed: %s", exc)
            return None

    async def set(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        *,
        tenant: str | None = None,
        namespace: str | None = None,
    ) -> None:
        """Set retrieval results in cache.

        Args:
            query: Query string.
            chunks: List of chunk dictionaries.
            tenant: Optional tenant scope (Sprint 2.1).
            namespace: Optional namespace scope.

        """
        client = self._ensure_client()
        try:
            await client.cache_set(
                self._key(query, tenant=tenant, namespace=namespace),
                orjson.dumps(chunks),
                self._ttl,
            )
        except Exception as exc:
            logger.debug("L3 cache set failed: %s", exc)

    async def invalidate(
        self, query: str, *, tenant: str | None = None, namespace: str | None = None
    ) -> None:
        """Invalidate cache entry.

        Args:
            query: Query string.
            tenant: Optional tenant scope (Sprint 2.1).
            namespace: Optional namespace scope.

        """
        client = self._ensure_client()
        try:
            await client.cache_delete(
                self._key(query, tenant=tenant, namespace=namespace)
            )
        except Exception as exc:
            logger.debug("L3 cache invalidate failed: %s", exc)

    async def flush(self) -> int:
        """Flush all cache entries.

        Удаляет только ключи текущего версионированного prefix
        (``rag:l3:v2:*``); legacy ``rag:l3:*`` не трогает.

        Returns:
            Number of deleted entries.

        """
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
            logger.debug("L3 cache flush failed: %s", exc)
            return 0
