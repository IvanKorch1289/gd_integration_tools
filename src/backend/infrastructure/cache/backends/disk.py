"""Disk cache backend — локальный файловый fallback для UnifiedCacheFacade.

Ponytail: minimal file-per-key backend без внешних зависимостей.
Ключ хэшируется SHA256; файлы раскладываются по подкаталогам для
избежания переполнения одной директории.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import aiofiles
import aiofiles.os

from src.backend.core.interfaces.cache import CacheBackend
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("DiskCacheBackend",)

_logger = get_logger("infrastructure.cache.disk")


class DiskCacheBackend(CacheBackend):
    """Файловый CacheBackend для tiered-fallback (L3 disk).

    Args:
        base_path: Корневой каталог для файлов кэша.
    """

    def __init__(self, base_path: str | Path) -> None:
        self._base = Path(base_path).expanduser().resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, key: str) -> Path:
        """Хэширует ключ и возвращает безопасный путь внутри base_path."""
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        # first 2 chars as shard prefix
        return self._base / digest[:2] / digest

    async def get(self, key: str) -> bytes | None:
        """Get value from disk cache.

        Args:
            key: Cache key.

        Returns:
            Cached bytes or None if not found.
        """
        path = self._safe_path(key)
        try:
            async with aiofiles.open(path, "rb") as fh:
                return await fh.read()
        except FileNotFoundError:
            return None
        except OSError as exc:
            _logger.debug("DiskCache get failed key=%s: %s", key, exc)
            return None

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set value in disk cache.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Ignored (disk backend has no per-key TTL).
        """
        del ttl  # disk backend ignores per-key TTL
        path = self._safe_path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            async with aiofiles.open(tmp, "wb") as fh:
                await fh.write(value)
            await aiofiles.os.replace(str(tmp), str(path))
        except OSError as exc:
            _logger.debug("DiskCache set failed key=%s: %s", key, exc)

    async def delete(self, *keys: str) -> None:
        """Delete values from disk cache.

        Args:
            keys: Cache keys to delete.
        """
        for key in keys:
            path = self._safe_path(key)
            try:
                await aiofiles.os.remove(str(path))
            except FileNotFoundError:
                pass
            except OSError as exc:
                _logger.debug("DiskCache delete failed key=%s: %s", key, exc)

    async def delete_pattern(self, pattern: str) -> None:
        """Delete values matching pattern (no-op for disk cache).

        Args:
            pattern: Glob pattern (ignored, disk cache doesn't support pattern delete).
        """
        def _sync() -> None:
            for path in self._base.rglob("*"):
                if path.is_file() and not path.name.endswith(".tmp"):
                    # key cannot be recovered from hash; skip pattern delete
                    pass

        await asyncio.to_thread(_sync)
        # Disk backend does not support pattern delete efficiently without
        # maintaining an index. delete_pattern is a no-op for disk fallback.

    async def exists(self, key: str) -> bool:
        """Check if key exists in disk cache.

        Args:
            key: Cache key.

        Returns:
            True if key exists, False otherwise.
        """
        path = self._safe_path(key)
        try:
            return await aiofiles.os.path.exists(str(path))
        except OSError as exc:
            _logger.debug("DiskCache exists failed key=%s: %s", key, exc)
            return False
