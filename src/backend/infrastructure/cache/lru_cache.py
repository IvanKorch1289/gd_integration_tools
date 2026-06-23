"""L1 in-process LRU cache на ``cachetools.TTLCache`` (Sprint 3 W1 К4).

Реализует tier L1 для 3-tier router (L1 in-proc → L2 redis → L3 semantic).
Поддерживает TTL, max_size, async API и Prometheus-метрики hit/miss/set
(noop-fallback при отсутствии ``prometheus_client``).

В отличие от существующего :class:`MemoryBackend` хранит произвольные
объекты (не только ``bytes``) и инкрементирует метрики прямо на каждом
обращении, что нужно роутеру для расчёта hit-rate per tier.
"""

from __future__ import annotations

import asyncio
from typing import Any

from cachetools import TTLCache

from src.backend.core.logging import get_logger

logger = get_logger("infrastructure.cache.lru")

__all__ = ("LruMemoryCache",)

# Глобальные lazy-инициализированные prometheus-счётчики. Они общие на
# процесс, чтобы несколько инстансов LruMemoryCache не плодили дубликаты
# в реестре Prometheus (``Counter`` уникален по имени).
_metric_hits: Any = None
_metric_misses: Any = None
_metric_sets: Any = None
_metrics_initialized = False


def _ensure_metrics() -> None:
    """Lazy-импорт ``prometheus_client`` + одноразовая регистрация Counter.

    При отсутствии библиотеки или сбое регистрации метрики становятся no-op
    (значения остаются ``None``). Повторный вызов — идемпотентен.
    """
    global _metric_hits, _metric_misses, _metric_sets, _metrics_initialized
    if _metrics_initialized:
        return
    try:
        from src.backend.infrastructure.observability.metrics_registry import (
            metrics_registry,
        )

        _metric_hits = metrics_registry.counter(
            "lru_cache_hits_total",
            "Кол-во cache-hit в L1 LruMemoryCache",
            labels=("scope",),
        )
        _metric_misses = metrics_registry.counter(
            "lru_cache_misses_total",
            "Кол-во cache-miss в L1 LruMemoryCache",
            labels=("scope",),
        )
        _metric_sets = metrics_registry.counter(
            "lru_cache_sets_total",
            "Кол-во set-операций в L1 LruMemoryCache",
            labels=("scope",),
        )
    except ImportError:
        logger.debug("MetricsRegistry недоступен — LruMemoryCache в no-op metrics")
    finally:
        _metrics_initialized = True


class LruMemoryCache:
    """Async TTL+LRU кэш с метриками hit/miss/set.

    Args:
        max_size: Максимальное число записей; при превышении вытесняется
            наименее недавно используемая запись.
        ttl_seconds: Время жизни записи в секундах. ``cachetools.TTLCache``
            применяет TTL глобально на кэш; per-key override не нужен в
            L1-сценарии (router выставляет одинаковый TTL для tier).
        scope: Логическое имя кэша (для labels метрик), например ``"l1-ai"``.

    Note:
        Совместим с :class:`core.interfaces.cache.CacheBackend`, но
        не наследует от него — храним произвольные Python-объекты, а не
        ``bytes``. Если потребуется serialised-fallback — оборачивать
        снаружи в :class:`MemoryBackend`.
    """

    def __init__(
        self, *, max_size: int = 1024, ttl_seconds: int = 300, scope: str = "l1"
    ) -> None:
        if max_size <= 0:
            raise ValueError("max_size должен быть положительным")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds должен быть положительным")
        self._scope = scope
        self._cache: TTLCache[str, Any] = TTLCache(maxsize=max_size, ttl=ttl_seconds)
        self._lock = asyncio.Lock()
        _ensure_metrics()

    @property
    def scope(self) -> str:
        """Логическое имя кэша (label для Prometheus)."""
        return self._scope

    @property
    def max_size(self) -> int:
        """Максимальный размер кэша (read-only)."""
        return int(self._cache.maxsize) if self._cache.maxsize is not None else 0

    @property
    def ttl_seconds(self) -> float:
        """Время жизни записи в секундах (read-only)."""
        return self._cache.ttl

    def _record_local_hit(self) -> None:
        """Updates local metrics snapshot for admin API."""
        try:
            from src.backend.infrastructure.cache.metrics_collector import (
                record_lru_hit,
            )

            record_lru_hit(self._scope)
        except ImportError:
            pass  # metrics_collector not available

    def _record_local_miss(self) -> None:
        """Updates local metrics snapshot for admin API."""
        try:
            from src.backend.infrastructure.cache.metrics_collector import (
                record_lru_miss,
            )

            record_lru_miss(self._scope)
        except ImportError:
            pass  # metrics_collector not available

    async def get(self, key: str) -> Any | None:
        """Возвращает значение по ключу или ``None`` (с инкрементом метрики).

        Args:
            key: Строковый ключ записи.

        Returns:
            Сохранённое значение либо ``None`` при miss / expiry.
        """
        async with self._lock:
            value = self._cache.get(key)
        if value is None:
            self._record_local_miss()
            if _metric_misses is not None:
                _metric_misses.labels(scope=self._scope).inc()
            return None
        self._record_local_hit()
        if _metric_hits is not None:
            _metric_hits.labels(scope=self._scope).inc()
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Сохраняет значение в кэше.

        Args:
            key: Строковый ключ.
            value: Произвольный Python-объект.
            ttl: Игнорируется (cachetools.TTLCache использует глобальный
                TTL на весь кэш). Параметр оставлен для API-совместимости
                с :class:`CacheBackend`.
        """
        del ttl  # API-совместимость
        async with self._lock:
            self._cache[key] = value
        if _metric_sets is not None:
            _metric_sets.labels(scope=self._scope).inc()

    async def invalidate(self, *keys: str) -> None:
        """Удаляет запись(-и) из кэша; отсутствующие ключи игнорируются."""
        if not keys:
            return
        async with self._lock:
            for key in keys:
                self._cache.pop(key, None)

    async def clear(self) -> None:
        """Полностью очищает кэш."""
        async with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """Текущее число записей в кэше (для отладки и admin-endpoint).

        Заметка: метод намеренно синхронный — Python ``__len__`` обязан
        возвращать ``int`` (не coroutine), а ``or``-fallback в коде
        вызывает ``__bool__``→``__len__`` неявно. ``size()`` безопасен
        для использования в boolean-контексте.
        """
        return len(self._cache)
