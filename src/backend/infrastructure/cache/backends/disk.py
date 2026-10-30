"""Disk cache backend — локальный файловый fallback для UnifiedCacheFacade.

Ponytail: minimal file-per-key backend без внешних зависимостей.
Ключ хэшируется SHA256; файлы раскладываются по подкаталогам для
избежания переполнения одной директории.

Cycle 168 (PROD_READINESS_LOGGING_CACHE_2026-10-20 §1.1): per-key TTL
реализован через expiry sidecar (``.expires`` файл рядом с data файлом).
``get()`` проверяет expiry и удаляет файл при истечении. ``set()``
записывает ``expires_at`` в sidecar при наличии ``ttl``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import time
from pathlib import Path

import aiofiles
import aiofiles.os

from src.backend.core.interfaces.cache import CacheBackend
from src.backend.core.logging import get_logger

__all__ = ("DiskCacheBackend",)

_logger = get_logger("infrastructure.cache.disk")


class DiskCacheBackend(CacheBackend):
    """Файловый CacheBackend для tiered-fallback (L3 disk).

    Cycle 168: per-key TTL через sidecar ``.expires`` файл.
    ``set(key, value, ttl=60)`` записывает ``expires_at`` рядом с данными;
    ``get(key)`` проверяет sidecar и удаляет просроченное значение.

    Args:
        base_path: Корневой каталог для файлов кэша.

    """

    _EXPIRY_SUFFIX = ".expires"

    def __init__(self, base_path: str | Path) -> None:
        self._base = Path(base_path).expanduser().resolve()
        self._base.mkdir(parents=True, exist_ok=True)
        # In-memory индекс записанных ключей — нужен для pattern-delete
        # (из файла имя ключа не восстановить: ключ хэшируется SHA256).
        # Wave 18 (ADR-0391), дефект 8.
        self._keys: set[str] = set()
        # ADR-0401: tag-индекс ``{tag: {key, ...}}`` — без него
        # ``CacheInvalidator.delete_by_tag`` не мог почистить L3-тир
        # (backend не реализовывал ``delete_by_tag`` вообще).
        self._tags: dict[str, set[str]] = {}

    def _safe_path(self, key: str) -> Path:
        """Хэширует ключ и возвращает безопасный путь внутри base_path."""
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        # first 2 chars as shard prefix
        return self._base / digest[:2] / digest

    def _expiry_path(self, key: str) -> Path:
        """Возвращает путь к sidecar-файлу с ``expires_at`` (Unix seconds)."""
        return self._safe_path(key).with_name(
            self._safe_path(key).name + self._EXPIRY_SUFFIX
        )

    async def _is_expired(self, key: str) -> bool:
        """True если sidecar указывает на прошедшее время.

        Отсутствие sidecar = no expiry (для backward-compat с pre-cycle-168
        файлами).
        """
        ep = self._expiry_path(key)
        try:
            async with aiofiles.open(ep, "rb") as fh:
                raw = await fh.read()
        except FileNotFoundError:
            return False
        except OSError as exc:
            _logger.debug("DiskCache expiry read failed key=%s: %s", key, exc)
            return False
        try:
            expires_at = int(raw.decode("utf-8").strip())
        except (ValueError, UnicodeDecodeError):
            return False
        return time.time() >= expires_at

    async def _cleanup_expired(self, key: str) -> None:
        """Удаляет data+sidecar для просроченного ключа (best-effort)."""
        for p in (self._safe_path(key), self._expiry_path(key)):
            try:
                await aiofiles.os.remove(str(p))
            except FileNotFoundError:
                pass
            except OSError as exc:
                _logger.debug("DiskCache cleanup failed key=%s: %s", key, exc)

    async def get(self, key: str) -> bytes | None:
        """Get value from disk cache.

        Cycle 168: проверяет expiry sidecar. Возвращает ``None`` и удаляет
        data+sidecar при истечении TTL.

        Args:
            key: Cache key.

        Returns:
            Cached bytes or None if not found / expired.

        """
        if await self._is_expired(key):
            await self._cleanup_expired(key)
            return None
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

        Cycle 168: ``ttl`` honored через ``.expires`` sidecar. При ``ttl=None``
        sidecar не создаётся → значение хранится без TTL (backward-compat).

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: TTL в секундах; ``None`` — без expiry.

        """
        path = self._safe_path(key)
        expiry_path = self._expiry_path(key)
        self._keys.add(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            async with aiofiles.open(tmp, "wb") as fh:
                await fh.write(value)
            await aiofiles.os.replace(str(tmp), str(path))
            if ttl is not None:
                expires_at = int(time.time()) + int(ttl)
                tmp_e = expiry_path.with_suffix(expiry_path.suffix + ".tmp")
                async with aiofiles.open(tmp_e, "wb") as fh:
                    await fh.write(str(expires_at).encode("utf-8"))
                await aiofiles.os.replace(str(tmp_e), str(expiry_path))
            else:
                # best-effort cleanup stale sidecar (если раньше был TTL)
                try:
                    await aiofiles.os.remove(str(expiry_path))
                except FileNotFoundError:
                    pass
        except OSError as exc:
            _logger.debug("DiskCache set failed key=%s: %s", key, exc)

    async def delete(self, *keys: str) -> None:
        """Delete values from disk cache (включая expiry sidecar).

        Cycle 168: удаляет data + ``.expires`` sidecar (cycle 168 TTL).

        Args:
            keys: Cache keys.

        """
        for key in keys:
            self._keys.discard(key)
            self._forget_key(key)
            await self._remove_files(key)

    async def _remove_files(self, key: str) -> None:
        """Удалить data-файл + expiry sidecar ключа (best-effort).

        Args:
            key: Cache key.

        """
        for p in (self._safe_path(key), self._expiry_path(key)):
            try:
                await aiofiles.os.remove(str(p))
            except FileNotFoundError:
                pass
            except OSError as exc:
                _logger.debug("DiskCache delete failed key=%s: %s", key, exc)

    def _forget_key(self, key: str) -> None:
        """Убрать ключ из всех tag-групп.

        Args:
            key: Cache key.

        """
        for tag_keys in self._tags.values():
            tag_keys.discard(key)

    # ── Tag-index support (ADR-0401) ───────────────────────────────────
    #
    # Контракт совпадает с ``RedisBackend``: ``bind_key_to_tag`` создаёт
    # связь «тег → ключи», ``delete_by_tag`` удаляет все ключи тега.
    # Без этого ``CacheInvalidator`` не мог инвалидировать L3-тир.

    async def bind_key_to_tag(self, tag: str, key: str) -> None:
        """Привязывает cache key к тегу.

        Args:
            tag: Имя тега (например ``entity:orders``).
            key: Cache key.

        """
        self._tags.setdefault(tag, set()).add(key)

    async def delete_by_tag(self, tag: str) -> int:
        """Удаляет все ключи, привязанные к тегу.

        Args:
            tag: Имя тега.

        Returns:
            Число удалённых ключей.

        """
        keys = self._tags.pop(tag, set())
        for key in keys:
            self._keys.discard(key)
            self._forget_key(key)
            await self._remove_files(key)
        return len(keys)

    async def delete_pattern(self, pattern: str) -> None:
        """Delete values matching pattern.

        Ключи хэшируются (SHA256) → из имени файла ключ не восстановить.
        Поэтому backend держит in-memory индекс ключей, записанных через
        ``set()``, и удаляет их по glob-паттерну.

        ponytail: потолок решения — индекс живёт в памяти процесса; после
        рестарта ранее записанные ключи неизвестны и pattern-delete их не
        заденет. Апгрейд — on-disk индекс (key → hash) рядом с данными.

        Args:
            pattern: Glob pattern (например ``"ns:*"``).

        """
        matched = [key for key in self._keys if fnmatch.fnmatch(key, pattern)]
        for key in matched:
            self._keys.discard(key)
            self._forget_key(key)
            await self._remove_files(key)

    async def delete_by_pattern(self, pattern: str) -> int:
        """Удаляет ключи по паттерну и возвращает их количество.

        Args:
            pattern: Glob pattern.

        Returns:
            Число удалённых ключей.

        """
        matched = [key for key in self._keys if fnmatch.fnmatch(key, pattern)]
        await self.delete_pattern(pattern)
        return len(matched)

    async def exists(self, key: str) -> bool:
        """Check if key exists in disk cache.

        Cycle 271 (audit HIGH-08): раньше проверялось только наличие файла,
        поэтому для просроченного ключа возвращалось ``True`` — stale-результат
        прямо в обход ``get()``, который sidecar проверяет. Теперь expiry
        проверяется так же, как в ``get()``.

        Args:
            key: Cache key.

        Returns:
            True если ключ существует **и не просрочен**, иначе False.

        """
        path = self._safe_path(key)
        try:
            if not await aiofiles.os.path.exists(str(path)):
                return False
            return not await self._is_expired(key)
        except OSError as exc:
            _logger.debug("DiskCache exists failed key=%s: %s", key, exc)
            return False
