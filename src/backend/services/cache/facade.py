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

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from src.backend.core.cache.facade import UnifiedCacheFacade as _CoreUnifiedCacheFacade
from src.backend.core.config.services.cache import cache_settings
from src.backend.core.interfaces.cache import CacheBackend
from src.backend.core.logging import get_logger

__all__ = ("CacheResult", "UnifiedCacheFacade")

_logger = get_logger("services.cache.facade")

# Cycle 168 (PROD_READINESS_LOGGING_CACHE_2026-10-20 §3): log throttling.
# При недоступности primary (Redis) каждый ``get_ns`` логирует WARNING.
# В production это приводит к log-spam (5000 warnings/sec observed в
# benchmark) → backpressure в batching_router → потеря логов.
#
# Решение: time-window based throttle. Первое предупреждение за window
# выводится на WARNING; последующие — на DEBUG. Через 60s counter
# сбрасывается. Это сохраняет видимость инцидента без flooding.
_LOG_THROTTLE_WINDOW_SECONDS = 60.0
_log_throttle_counters: dict[str, tuple[float, int]] = defaultdict(
    lambda: (0.0, 0)
)


def _throttled_warning(
    *,
    backend: str,
    operation: str,
    key: str,
    error: BaseException,
) -> None:
    """WARNING первый за window; остальные DEBUG (throttle).

    Args:
        backend: Имя backend'а (``"primary"``, ``"memory"``, ``"disk"``).
        operation: Имя операции (``"get"``, ``"set"``, ``"delete"``).
        key: Cache key (для message).
        error: Exception, который произошёл.

    """
    bucket = f"{backend}.{operation}"
    now = time.monotonic()
    started_at, count = _log_throttle_counters[bucket]
    if now - started_at >= _LOG_THROTTLE_WINDOW_SECONDS:
        _log_throttle_counters[bucket] = (now, 1)
        _logger.warning(
            "Cache %s %s failed key=%s: %s (suppressing repeats for %.0fs)",
            backend,
            operation,
            key,
            error,
            _LOG_THROTTLE_WINDOW_SECONDS,
        )
        return
    _log_throttle_counters[bucket] = (started_at, count + 1)
    if count == 1:
        _logger.warning(
            "Cache %s %s failing (suppressed %d repeats in %.0fs window)",
            backend,
            operation,
            count,
            _LOG_THROTTLE_WINDOW_SECONDS,
        )
    else:
        _logger.debug(
            "Cache %s %s failed (suppressed): key=%s err=%s",
            backend,
            operation,
            key,
            error,
        )


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
            _throttled_warning(backend="primary", operation="get", key=full, error=exc)

        if self._memory is not None:
            try:
                value = await self._memory.get(full)
                if value is not None:
                    return CacheResult(value=value, hit=True, backend="memory")
            except Exception as exc:
                _throttled_warning(backend="memory", operation="get", key=full, error=exc)

        if self._disk is not None:
            try:
                value = await self._disk.get(full)
                if value is not None:
                    return CacheResult(value=value, hit=True, backend="disk")
            except Exception as exc:
                _throttled_warning(backend="disk", operation="get", key=full, error=exc)

        return CacheResult(value=None, hit=False, backend="none")

    async def set_ns(
        self,
        key: str,
        value: bytes,
        ttl: int | None = None,
        tags: list[str] | None = None,
        namespace: str = "default",
    ) -> None:
        """Namespace-aware set (best-effort по всем уровням).

        Raises:
            ValueError: если размер значения превышает
                ``cache_settings.max_value_bytes`` (wave 18, ADR-0391,
                дефект 7) — значение не пишется ни в один tier.

        """
        self._assert("cache.write", namespace)
        full = self._full_key(namespace, key)
        self._assert_value_size(value)

        successful_writes = 0
        for name, backend in (
            ("primary", self._primary),
            ("memory", self._memory),
            ("disk", self._disk),
        ):
            if backend is None:
                continue
            try:
                await backend.set(full, value, ttl=ttl)
                successful_writes += 1
            except Exception as exc:
                _throttled_warning(backend=name, operation="set", key=full, error=exc)

        # Cycle 168 (PROD_READINESS §1.6): tag_index обновляется только
        # если хотя бы один backend принял запись. Иначе tag invalidation
        # в дальнейшем будет пытаться удалить несуществующие ключи.
        if tags and successful_writes > 0:
            ns_tags = self._tag_index.setdefault(namespace, {})
            for tag in tags:
                ns_tags.setdefault(tag, set()).add(key)
            await self._bind_tags_to_backends(full, tags)

    @staticmethod
    def _assert_value_size(value: bytes) -> None:
        """Проверяет лимит размера значения (wave 18, ADR-0391, дефект 7).

        Args:
            value: Значение, которое планируется записать.

        Raises:
            ValueError: значение больше ``cache_settings.max_value_bytes``.

        """
        max_bytes = cache_settings.max_value_bytes
        if max_bytes and len(value) > max_bytes:
            raise ValueError(
                f"Cache value too large: {len(value)} bytes exceeds "
                f"max_value_bytes={max_bytes}. Increase cache.max_value_bytes "
                f"or reduce payload size."
            )

    async def _bind_tags_to_backends(
        self, full_key: str, tags: list[str]
    ) -> None:
        """Регистрирует ключ в tag-индексах backend'ов (дефект 5).

        Backend'ы с нативной поддержкой тегов (``RedisBackend``) хранят
        индекс ``__cache_tag:{tag}`` — без привязки ``CacheInvalidator``
        не может удалить ключи по тегу.

        Args:
            full_key: Полный (namespace-scoped) ключ.
            tags: Список тегов.

        """
        for backend in (self._primary, self._memory, self._disk):
            if backend is None:
                continue
            binder = getattr(backend, "bind_key_to_tag", None)
            if binder is None:
                continue
            for tag in tags:
                try:
                    await binder(tag, full_key)
                except Exception as exc:
                    _throttled_warning(
                        backend=type(backend).__name__,
                        operation="bind_tag",
                        key=full_key,
                        error=exc,
                    )

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
                _throttled_warning(backend=name, operation="delete", key=str(full_keys), error=exc)

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
                _throttled_warning(backend=name, operation="exists", key=full, error=exc)
        return False

    async def delete_pattern_ns(self, pattern: str, namespace: str = "default") -> None:
        """Namespace-aware delete_pattern (все уровни: primary/memory/disk).

        Wave 18 (ADR-0391), дефект 8: disk-tier тоже чистится. Раньше он
        намеренно исключался (pattern-delete в disk был no-op) → после
        падения Redis клиент получал stale-значения из L3.

        Для disk pattern-delete работает по in-memory индексу ключей
        (см. ``DiskCacheBackend.delete_pattern``) — tenant-scoped паттерн
        применяется на уровне wrapper'а.

        Args:
            pattern: Glob pattern.
            namespace: Namespace ключей.

        """
        self._assert("cache.write", namespace)
        full_pattern = self._full_key(namespace, pattern)

        for name, backend in (
            ("primary", self._primary),
            ("memory", self._memory),
            ("disk", self._disk),
        ):
            if backend is None:
                continue
            try:
                await backend.delete_pattern(full_pattern)
            except Exception as exc:
                _throttled_warning(backend=name, operation="delete_pattern", key=full_pattern, error=exc)

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
