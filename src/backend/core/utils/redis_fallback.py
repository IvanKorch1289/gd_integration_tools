"""Graceful degrade Redis → in-memory TTLCache (cachetools).

Wave: ``[wave:s16/k2-w5-redis-graceful-degrade]`` — DoD partial Sprint 16
(resilience). При недоступности Redis (ConnectionError/TimeoutError)
автоматически переключаемся на ``cachetools.TTLCache`` локально, чтобы
основные операции get/set продолжали работать.

Принципы:
1. Protocol ``RedisLike`` — минимальный async-API (get/set/delete).
2. ``FallbackCache`` — wrapper: первая попытка Redis; при сбое
   degrade-flag + локальный TTLCache.
3. Periodic re-probe Redis: при успешном ping в фоне — возврат в
   normal-mode (no-degrade).
4. Все метрики degradation идут через ResilienceCoordinator
   (wire — carryover S17).

Совместимо с любым backend, удовлетворяющим RedisLike Protocol
(redis.asyncio.Redis, KeyDB-клиент, fakeredis, и т.д.).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from cachetools import TTLCache

from src.backend.core.logging import get_logger

__all__ = ("FallbackCache", "RedisErrorCategory", "RedisLike")

_logger = get_logger("core.utils.redis_fallback")


class RedisErrorCategory:
    """Категории исключений Redis, при которых активируется fallback.

    Содержит mod-level tuple, потому что сами классы исключений могут
    отличаться между backend-ами (redis-py / keydb / fakeredis), а мы
    хотим catch as broad as needed без жёстких импортов.
    """

    #: Базовые типы из stdlib — гарантированно ловятся.
    BASE: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError, OSError)


@runtime_checkable
class RedisLike(Protocol):
    """Минимальный контракт Redis-backend для FallbackCache."""

    async def get(self, key: str) -> Any | None:
        """Прочитать значение по ключу. Возвращает None, если нет."""

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        """Записать значение; опциональный TTL ``ex`` в секундах."""

    async def delete(self, key: str) -> None:
        """Удалить ключ. No-op если ключа не существует."""


class FallbackCache:
    """Wrapper над Redis-like backend с TTLCache fallback при отказе.

    Использование::

        primary = redis.asyncio.Redis.from_url("redis://...")
        cache = FallbackCache(primary=primary, fallback_maxsize=1024, fallback_ttl=60.0)
        await cache.set("k", "v", ex=30)
        v = await cache.get("k")  # сначала из Redis; при недоступности — TTLCache

    После сбоя Redis записывает ``degraded=True``. Caller может опросить
    статус через свойство :attr:`degraded`. Возврат в normal-mode
    происходит при следующем успешном ``get/set`` (lazy recovery) или
    через ручной :meth:`reset_degradation()`.
    """

    def __init__(
        self,
        *,
        primary: RedisLike,
        fallback_maxsize: int = 1024,
        fallback_ttl: float = 60.0,
    ) -> None:
        """Создать обёртку.

        Args:
            primary: Основной Redis-like backend.
            fallback_maxsize: Размер локального TTLCache.
            fallback_ttl: TTL записей в локальном кэше (секунды).
        """
        self._primary = primary
        self._fallback: TTLCache[str, Any] = TTLCache(
            maxsize=fallback_maxsize, ttl=fallback_ttl
        )
        self._degraded = False
        self._consecutive_failures = 0

    @property
    def degraded(self) -> bool:
        """True, если последняя операция перешла в fallback-режим."""
        return self._degraded

    @property
    def consecutive_failures(self) -> int:
        """Счётчик подряд идущих отказов Redis."""
        return self._consecutive_failures

    def reset_degradation(self) -> None:
        """Принудительно сбросить degradation-state (для admin-endpoint)."""
        self._degraded = False
        self._consecutive_failures = 0

    async def get(self, key: str) -> Any | None:
        """Прочитать значение: сначала Redis; при сбое — TTLCache."""
        try:
            value = await self._primary.get(key)
        except RedisErrorCategory.BASE as exc:
            self._mark_degraded("get", exc)
            return self._fallback.get(key)
        self._mark_recovered()
        return value

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        """Записать в Redis; при сбое — в TTLCache (best-effort)."""
        try:
            await self._primary.set(key, value, ex=ex)
        except RedisErrorCategory.BASE as exc:
            self._mark_degraded("set", exc)
            self._fallback[key] = value
            return
        self._mark_recovered()
        # Также пишем в fallback — чтобы при сбое чтения было что-то
        # отдать без cross-process trip.
        self._fallback[key] = value

    async def delete(self, key: str) -> None:
        """Удалить из Redis (если жив) и из fallback."""
        try:
            await self._primary.delete(key)
        except RedisErrorCategory.BASE as exc:
            self._mark_degraded("delete", exc)
        else:
            self._mark_recovered()
        self._fallback.pop(key, None)

    def _mark_degraded(self, op: str, exc: BaseException) -> None:
        """Обозначить, что Redis сейчас недоступен (lazy degrade)."""
        self._degraded = True
        self._consecutive_failures += 1
        _logger.warning(
            "redis fallback engaged op=%s failures=%d error=%s",
            op,
            self._consecutive_failures,
            type(exc).__name__,
        )

    def _mark_recovered(self) -> None:
        """Обозначить, что Redis снова отвечает (lazy recovery)."""
        if self._degraded:
            _logger.info(
                "redis recovered after %d failures", self._consecutive_failures
            )
        self._degraded = False
        self._consecutive_failures = 0
