"""AiocacheBackend — ``CacheBackend`` ABC реализация поверх ``aiocache``.

W4 P1-6 (cycle 152, MINIMAX plan):): opt-in backend для тех, кто хочет
использовать ``aiocache`` API напрямую (memory backend с TTL + декоратор
``@cached``/``@cached_stampede``).

Использование:

    from src.backend.infrastructure.cache.backends.aiocache_backend import (  # noqa: F401 — re-export
        AiocacheMemoryBackend,
    )

    backend = AiocacheMemoryBackend(maxsize=1000, default_ttl=3600)
    await backend.set("key", b"value", ttl=60)
    value = await backend.get("key")

Или через :func:`create_cache_backend` factory:

    backend = create_cache_backend("aiocache-memory", maxsize=500)

Note:

    * ``aiocache`` доступен ТОЛЬКО через ``[caching]`` optional extra
      (``pip install -e ".[caching]"``) — см. ADR-0311.
    * Этот backend НЕ заменти custom :class:`CachingDecorator` —
      последний поддерживает SWR, envelope и pattern invalidation,
      которых нет в aiocache.
    * Для простых in-memory + Redis сценариев — alternative path
      (``MemoryBackend`` уже использует ``cachetools.TTLCache``).

Refs: ADR-0311 (W4 P1-6 aiocache evaluation + hybrid decision).
"""

from __future__ import annotations

from src.backend.core.interfaces.cache import CacheBackend

__all__ = ("AiocacheMemoryBackend",)


class AiocacheBackendImportError(ImportError):
    """Raised when aiocache is not installed but backend is requested."""


def _ensure_aiocache_available() -> None:
    """Check that aiocache is installed; raise helpful error if not."""
    try:
        import aiocache  # noqa: F401
    except ImportError as e:
        raise AiocacheBackendImportError(
            "aiocache is required for AiocacheMemoryBackend. "
            "Install via `pip install -e \".[caching]\"` "
            "or `uv sync --extra caching`."
        ) from e


class AiocacheMemoryBackend(CacheBackend):
    """Memory backend на ``aiocache.SimpleMemoryBackend``.

    Implements :class:`core.interfaces.CacheBackend` поверх
    ``aiocache.Cache`` с in-memory storage. TTL per-key через
    ``aiocache``-native API.

    Args:
        maxsize: Максимальное число записей (best-effort, aiocache не
            жёстко ограничивает размер).
        default_ttl: Default TTL в секундах для ``set`` без явного ``ttl``.

    Note:
        ``delete_pattern`` НЕ реализован оптимально — aiocache имеет
        только ``delete(key)``. Этот backend делает простой
        prefix-match через ``_keys()`` (memory backend exposes keys)
        с fnmatch-семантикой. Для production pattern deletion
        рекомендуется :class:`RedisBackend`.
    """

    def __init__(self, maxsize: int = 1000, default_ttl: int = 3600) -> None:
        _ensure_aiocache_available()
        from aiocache import Cache  # noqa: WPS433 — lazy after check
        from aiocache.backends.memory import SimpleMemoryCache  # noqa: WPS433

        self._default_ttl = default_ttl
        self._maxsize = maxsize
        self._cache: Cache = Cache(
            cache_class=SimpleMemoryCache,
            ttl=default_ttl,
        )

    async def get(self, key: str) -> bytes | None:
        """Get cached value by key.

        Args:
            key: Cache key (str).

        Returns:
            Cached bytes or None if absent/expired.
        """
        value = await self._cache.get(key)
        if value is None:
            return None
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")
        # Fallback: serialize via pickle (NOT for untrusted data).
        import pickle

        return pickle.dumps(value)

    async def set(
        self, key: str, value: bytes, ttl: int | None = None
    ) -> None:
        """Store value with TTL.

        Args:
            key: Cache key.
            value: Bytes payload.
            ttl: TTL в seconds, или ``None`` для ``default_ttl``.
        """
        await self._cache.set(
            key,
            value,
            ttl=ttl if ttl is not None else self._default_ttl,
        )

    async def delete(self, *keys: str) -> None:
        """Delete one or more keys.

        Args:
            *keys: Variable number of keys to delete.
        """
        for key in keys:
            await self._cache.delete(key)

    async def delete_pattern(self, pattern: str) -> None:
        """Delete all keys matching pattern (fnmatch-style).

        Note:
            aiocache memory backend does NOT expose keys enumeration
            natively. We approximate via Cache._cache dict (private API).
            Prefer :class:`RedisBackend` для production pattern deletion.

        Args:
            pattern: fnmatch-style pattern (e.g., ``"user:*:profile"``).
        """
        import fnmatch

        cache_dict = getattr(self._cache, "_cache", {})
        keys_to_delete = [
            key for key in list(cache_dict.keys())
            if fnmatch.fnmatchcase(key, pattern)
        ]
        if keys_to_delete:
            await self.delete(*keys_to_delete)

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache.

        Args:
            key: Cache key.

        Returns:
            True if key exists.
        """
        return await self._cache.exists(key) > 0

    async def close(self) -> None:
        """Close cache connection (no-op for SimpleMemoryCache)."""
        await self._cache.close()