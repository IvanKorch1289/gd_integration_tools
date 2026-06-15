"""UnifiedCacheFacade — capability-checked фасад кэша с tiered fallback.

P1 S133 W4: Redis ↔ memory ↔ disk fallback через единый API.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.backend.core.interfaces.cache import CacheBackend
from src.backend.core.logging import get_logger

__all__ = ("CacheResult", "UnifiedCacheFacade")

_logger = get_logger("services.cache.facade")

CapabilityChecker = Callable[[str, str, str | None], None]


@dataclass(frozen=True, slots=True)
class CacheResult:
    """Результат чтения из UnifiedCacheFacade.

    Attributes:
        value: Значение или None при miss.
        hit: True если значение найдено.
        backend: Имя backend'а, откуда пришло значение.
    """

    value: bytes | None
    hit: bool
    backend: str


class UnifiedCacheFacade:
    """Capability-checked cache facade с tiered fallback.

    Args:
        primary: Основной бэкенд (Redis/KeyDB/etc).
        memory_fallback: L2 in-memory fallback (обычно MemoryBackend).
        disk_fallback: L3 disk fallback (DiskCacheBackend).
        capability_check: Опц. callback ``CapabilityGate.check``.
        plugin: Имя caller'а для capability-event.
    """

    def __init__(
        self,
        primary: CacheBackend,
        *,
        memory_fallback: CacheBackend | None = None,
        disk_fallback: CacheBackend | None = None,
        capability_check: CapabilityChecker | None = None,
        plugin: str = "extension",
    ) -> None:
        self._primary = primary
        self._memory = memory_fallback
        self._disk = disk_fallback
        self._check = capability_check
        self._plugin = plugin

    def _full_key(self, namespace: str, key: str) -> str:
        return f"{namespace}:{key}"

    def _assert(self, capability: str, namespace: str) -> None:
        if self._check is not None:
            self._check(self._plugin, capability, namespace)

    async def get(self, key: str, namespace: str = "default") -> CacheResult:
        """Прочитать ключ из кэша с fallback chain."""
        self._assert("cache.read", namespace)
        full = self._full_key(namespace, key)

        try:
            value = await self._primary.get(full)
            if value is not None:
                return CacheResult(value=value, hit=True, backend="primary")
        except Exception as exc:
            _logger.warning("Cache primary get failed key=%s: %s", full, exc)

        if self._memory is not None:
            try:
                value = await self._memory.get(full)
                if value is not None:
                    return CacheResult(value=value, hit=True, backend="memory")
            except Exception as exc:
                _logger.warning("Cache memory get failed key=%s: %s", full, exc)

        if self._disk is not None:
            try:
                value = await self._disk.get(full)
                if value is not None:
                    return CacheResult(value=value, hit=True, backend="disk")
            except Exception as exc:
                _logger.warning("Cache disk get failed key=%s: %s", full, exc)

        return CacheResult(value=None, hit=False, backend="none")

    async def set(
        self, key: str, value: bytes, ttl: int | None = None, namespace: str = "default"
    ) -> None:
        """Записать ключ в кэш (best-effort по всем уровням)."""
        self._assert("cache.write", namespace)
        full = self._full_key(namespace, key)

        for name, backend in (
            ("primary", self._primary),
            ("memory", self._memory),
            ("disk", self._disk),
        ):
            if backend is None:
                continue
            try:
                await backend.set(full, value, ttl=ttl)
            except Exception as exc:
                _logger.warning("Cache %s set failed key=%s: %s", name, full, exc)

    async def delete(self, *keys: str, namespace: str = "default") -> None:
        """Удалить ключи из всех уровней."""
        self._assert("cache.write", namespace)
        full_keys = [self._full_key(namespace, k) for k in keys]

        for name, backend in (
            ("primary", self._primary),
            ("memory", self._memory),
            ("disk", self._disk),
        ):
            if backend is None:
                continue
            try:
                await backend.delete(*full_keys)
            except Exception as exc:
                _logger.warning("Cache %s delete failed: %s", name, exc)

    async def exists(self, key: str, namespace: str = "default") -> bool:
        """Проверить существование ключа (с fallback)."""
        self._assert("cache.read", namespace)
        full = self._full_key(namespace, key)

        for name, backend in (
            ("primary", self._primary),
            ("memory", self._memory),
            ("disk", self._disk),
        ):
            if backend is None:
                continue
            try:
                if await backend.exists(full):
                    return True
            except Exception as exc:
                _logger.warning("Cache %s exists failed key=%s: %s", name, full, exc)
        return False

    async def delete_pattern(self, pattern: str, namespace: str = "default") -> None:
        """Удалить ключи по glob-шаблону (только primary/memory)."""
        self._assert("cache.write", namespace)
        full_pattern = self._full_key(namespace, pattern)

        for name, backend in (
            ("primary", self._primary),
            ("memory", self._memory),
        ):
            if backend is None:
                continue
            try:
                await backend.delete_pattern(full_pattern)
            except Exception as exc:
                _logger.warning("Cache %s delete_pattern failed: %s", name, exc)
