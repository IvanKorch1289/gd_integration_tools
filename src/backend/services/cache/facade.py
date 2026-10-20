"""UnifiedCacheFacade — capability-checked фасад кэша с tiered fallback.

P1 S133 W4: Redis ↔ memory ↔ disk fallback через единый API.

Cycle 165 (ADR-0352 Stage 2): этот фасад теперь ``extends``
:class:`core.cache.facade.UnifiedCacheFacade` ABC. Core ABC — canonical
interface; services facade добавляет:
  - ``*_ns`` методы (namespace-aware variants) с CacheResult observability
  - capability check (V15 R-V15-1 — plugin-runtime-gate)
  - facade-level tag tracking для backends без native tag support
  - tiered healthcheck

Layer rule: services → core (allowed). core → services (FORBIDDEN per
CLAUDE.md / tools/check_layers.py).

Migration (cycle 165):
  - get(key, namespace=...) → use ``get_ns(key, namespace)``
  - set(key, value, ttl, namespace=...) → use ``set_ns(...)``
  - delete(*keys, namespace=...) → use ``delete_ns(...)``
  - exists(key, namespace=...) → use ``exists_ns(...)``
  - delete_pattern(pattern, namespace=...) → use ``delete_pattern_ns(...)``

ABC-style methods (core ABC):
  - ``get(key) → bytes | None``
  - ``set(key, value, ttl_seconds, tags)``
  - ``delete(*keys)``
  - ``delete_by_tag(tag) → int``
  - ``exists(key) → bool``
  - ``healthcheck() → bool``
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.backend.core.cache.facade import UnifiedCacheFacade as _CoreUnifiedCacheFacade
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


class UnifiedCacheFacade(_CoreUnifiedCacheFacade):
    """Capability-checked cache facade с tiered fallback.

    Extends :class:`core.cache.facade.UnifiedCacheFacade` ABC. ABC methods
    (``get``, ``set``, ``delete``, ``delete_by_tag``, ``exists``,
    ``healthcheck``) используют namespace='default'. Namespace-aware
    варианты — ``*_ns`` методы.

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
        # Cycle 165: namespace-scoped tag index для backends без native tag.
        # _tag_index[namespace][tag] = set[key]
        self._tag_index: dict[str, dict[str, set[str]]] = {}

    def _full_key(self, namespace: str, key: str) -> str:
        return f"{namespace}:{key}"

    def _assert(self, capability: str, namespace: str) -> None:
        if self._check is not None:
            self._check(self._plugin, capability, namespace)

    # ─────────────── ABC methods (core cache interface) ───────────────

    async def get(self, key: str) -> bytes | None:
        """ABC impl: get(key) → bytes | None (namespace='default').

        Делегирует к ``get_ns(key, namespace='default')``.
        """
        result = await self.get_ns(key, namespace="default")
        return result.value

    async def set(
        self,
        key: str,
        value: bytes,
        ttl_seconds: int | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """ABC impl: set(key, value, ttl_seconds, tags) — namespace='default'.

        Если переданы ``tags``, регистрирует в ``_tag_index['default']``.
        """
        await self.set_ns(
            key, value, ttl=ttl_seconds, tags=tags, namespace="default"
        )

    async def delete(self, *keys: str) -> None:
        """ABC impl: delete(*keys) — namespace='default'."""
        await self.delete_ns(*keys, namespace="default")

    async def delete_by_tag(self, tag: str) -> int:
        """ABC impl: delete_by_tag(tag) — namespace='default'.

        Returns: кол-во удалённых ключей.
        """
        return await self.delete_by_tag_ns(tag, namespace="default")

    async def exists(self, key: str) -> bool:
        """ABC impl: exists(key) — namespace='default'."""
        return await self.exists_ns(key, namespace="default")

    async def healthcheck(self) -> bool:
        """ABC impl: True если хотя бы один backend доступен."""
        return await self.healthcheck_ns()

    # ─────────────── Namespace-aware methods (canonical API) ───────────────

    async def get_ns(self, key: str, namespace: str = "default") -> CacheResult:
        """Namespace-aware get → CacheResult с observability.

        Tries primary → memory → disk (3-tier fallback).
        """
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

    async def set_ns(
        self,
        key: str,
        value: bytes,
        ttl: int | None = None,
        tags: list[str] | None = None,
        namespace: str = "default",
    ) -> None:
        """Namespace-aware set (best-effort по всем уровням)."""
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

        # Tag tracking (facade-level, для non-Redis backends).
        if tags:
            ns_tags = self._tag_index.setdefault(namespace, {})
            for tag in tags:
                ns_tags.setdefault(tag, set()).add(key)

    async def delete_ns(self, *keys: str, namespace: str = "default") -> None:
        """Namespace-aware delete (все уровни)."""
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

        # Очищаем key из tag_index (во всех namespace).
        for ns_tags in self._tag_index.values():
            for tag_keys in ns_tags.values():
                for k in keys:
                    tag_keys.discard(k)

    async def exists_ns(self, key: str, namespace: str = "default") -> bool:
        """Namespace-aware exists (с fallback)."""
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

    async def delete_pattern_ns(self, pattern: str, namespace: str = "default") -> None:
        """Namespace-aware delete_pattern (только primary/memory)."""
        self._assert("cache.write", namespace)
        full_pattern = self._full_key(namespace, pattern)

        for name, backend in (("primary", self._primary), ("memory", self._memory)):
            if backend is None:
                continue
            try:
                await backend.delete_pattern(full_pattern)
            except Exception as exc:
                _logger.warning("Cache %s delete_pattern failed: %s", name, exc)

    async def delete_by_tag_ns(self, tag: str, namespace: str = "default") -> int:
        """Namespace-aware delete_by_tag (facade-level tracking).

        Strategy:
        1. Ищем keys в ``_tag_index[namespace][tag]``.
        2. Если есть — delete_ns(*keys, namespace).
        3. Очищаем tag entry.

        Returns:
            Кол-во удалённых ключей.
        """
        self._assert("cache.write", namespace)
        ns_tags = self._tag_index.get(namespace, {})
        keys = ns_tags.pop(tag, set())
        if keys:
            await self.delete_ns(*keys, namespace=namespace)
        return len(keys)

    async def healthcheck_ns(self) -> bool:
        """Tiered healthcheck — True если хотя бы один backend доступен."""
        for name, backend in (
            ("primary", self._primary),
            ("memory", self._memory),
            ("disk", self._disk),
        ):
            if backend is None:
                continue
            try:
                if hasattr(backend, "healthcheck"):
                    if await backend.healthcheck():
                        return True
                elif hasattr(backend, "get"):
                    # Fallback: probe с no-op get.
                    await backend.get("__healthcheck__")
                    return True
            except Exception as exc:
                _logger.debug("Cache %s healthcheck failed: %s", name, exc)
        return False