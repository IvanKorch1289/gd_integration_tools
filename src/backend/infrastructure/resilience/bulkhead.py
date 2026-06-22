"""Bulkhead — изоляция ресурсов через ограничение concurrency (ADR-005).

Bulkhead-паттерн предотвращает «заливание» всего приложения при отказе
одного даунстрима: разным ресурсам выделяются независимые semaphore-пулы.
В сочетании с per-tenant rate-limiter это защищает банковскую шину от
каскадных сбоев.

Реализация на ``asyncio.Semaphore`` — лёгкая, process-local. Для
кластерной координации используется RateLimiter на Redis
(``rate_limiter.py``).

Sprint 8A K2 W6 — стандартные defaults: :data:`BULKHEAD_DEFAULTS` хранит
sensible HighWatermark/LowWatermark для трёх типовых pool'ов (HTTP, DB,
Redis). См. :func:`get_default_bulkhead`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from src.backend.core.logging import get_logger
__all__ = (
    "BULKHEAD_DEFAULTS",
    "Bulkhead",
    "BulkheadDefaults",
    "BulkheadExhausted",
    "BulkheadRegistry",
    "get_bulkhead_registry",
    "get_default_bulkhead",
)

logger = get_logger("resilience.bulkhead")


class BulkheadExhausted(Exception):
    """Превышено время ожидания слота в bulkhead."""


@dataclass(slots=True)
class Bulkhead:
    """Semaphore-based isolation для одного ресурса.

    Attrs:
        name: Имя ресурса (``"external-skb"``, ``"postgres-orders"``).
        max_concurrent: Максимум одновременных операций.
        wait_timeout: Секунды ожидания свободного слота.
    """

    name: str
    max_concurrent: int = 32
    wait_timeout: float = 5.0
    _sem: asyncio.Semaphore | None = None

    def _ensure_sem(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.max_concurrent)
        return self._sem

    @asynccontextmanager
    async def guard(self) -> AsyncIterator[None]:
        """Заимствует слот; при таймауте поднимает ``BulkheadExhausted``."""
        sem = self._ensure_sem()
        try:
            await asyncio.wait_for(sem.acquire(), timeout=self.wait_timeout)
        except TimeoutError as exc:
            logger.warning(
                "Bulkhead '%s' exhausted (waited %.1fs, max=%d)",
                self.name,
                self.wait_timeout,
                self.max_concurrent,
            )
            raise BulkheadExhausted(
                f"bulkhead '{self.name}' exhausted after {self.wait_timeout}s"
            ) from exc
        try:
            yield
        finally:
            sem.release()


@dataclass(frozen=True, slots=True)
class BulkheadDefaults:
    """Sensible defaults для типовых backend-pool'ов (Sprint 8A K2 W6).

    Attributes:
        max_concurrent: HighWatermark — порог, выше которого новые
            запросы ждут освобождения слота (или fail-fast при timeout).
        low_watermark: LowWatermark — рекомендуемая загрузка, при которой
            пул считается "здоровым" (для adaptive scaling).
        wait_timeout: Таймаут ожидания свободного слота (секунды).
    """

    max_concurrent: int
    low_watermark: int
    wait_timeout: float = 5.0

    def __post_init__(self) -> None:
        """Валидация: 1 <= low_watermark <= max_concurrent."""
        if self.max_concurrent < 1:
            raise ValueError("max_concurrent должен быть >= 1")
        if not 1 <= self.low_watermark <= self.max_concurrent:
            raise ValueError("low_watermark должен быть в пределах [1, max_concurrent]")


# Sprint 8A K2 W6 — стандартные defaults для backend-pool'ов:
#   * http   — внешние HTTP-вызовы (httpx pool).
#   * db     — SQLAlchemy AsyncEngine sessions.
#   * redis  — redis.asyncio Redis connections.
# Источник цифр: PLAN.md V15 R-V15-14 (HTTP 100/80, DB 50/40, Redis 200/160).
BULKHEAD_DEFAULTS: dict[str, BulkheadDefaults] = {
    "http": BulkheadDefaults(max_concurrent=100, low_watermark=80),
    "db": BulkheadDefaults(max_concurrent=50, low_watermark=40),
    "redis": BulkheadDefaults(max_concurrent=200, low_watermark=160),
}


class BulkheadRegistry:
    """Глобальный registry Bulkhead-инстансов по имени ресурса."""

    def __init__(self) -> None:
        self._items: dict[str, Bulkhead] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        name: str,
        *,
        max_concurrent: int = 32,
        wait_timeout: float = 5.0,
        preset: str | None = None,
    ) -> Bulkhead:
        """Возвращает существующий Bulkhead или создаёт новый.

        Args:
            name: Логическое имя ресурса (``"external-skb"``).
            max_concurrent: HighWatermark (override; ignored если задан preset).
            wait_timeout: Таймаут ожидания слота (override; ignored если preset).
            preset: Имя стандартного preset'а из :data:`BULKHEAD_DEFAULTS`
                (``"http"`` / ``"db"`` / ``"redis"``). Перекрывает кастомные
                ``max_concurrent`` / ``wait_timeout``.

        Returns:
            :class:`Bulkhead` (singleton по ``name`` в этом registry).

        Raises:
            KeyError: Неизвестное имя preset'а.
        """
        if preset is not None:
            defaults = BULKHEAD_DEFAULTS[preset]
            max_concurrent = defaults.max_concurrent
            wait_timeout = defaults.wait_timeout
        async with self._lock:
            bh = self._items.get(name)
            if bh is None:
                bh = Bulkhead(
                    name=name, max_concurrent=max_concurrent, wait_timeout=wait_timeout
                )
                self._items[name] = bh
            return bh

    def list_names(self) -> list[str]:
        """Get list of registered bulkhead names.

        Returns:
            Sorted list of bulkhead names.
        """
        return sorted(self._items.keys())


@lru_cache(maxsize=1)
def get_bulkhead_registry() -> BulkheadRegistry:
    """Lazy singleton глобального ``BulkheadRegistry`` (Wave 6.1)."""
    return BulkheadRegistry()


async def get_default_bulkhead(preset: str) -> Bulkhead:
    """Возвращает Bulkhead для типового preset'а (Sprint 8A K2 W6).

    Логическое имя ресурса совпадает с preset'ом (``"http"`` / ``"db"`` /
    ``"redis"``); повторный вызов возвращает singleton.

    Args:
        preset: Имя preset'а из :data:`BULKHEAD_DEFAULTS`.

    Returns:
        Bulkhead с дефолтами по preset'у.
    """
    registry = get_bulkhead_registry()
    return await registry.get_or_create(preset, preset=preset)


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat ``registry``."""
    if name == "registry":
        return get_bulkhead_registry()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
