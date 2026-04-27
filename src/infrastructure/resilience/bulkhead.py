"""Bulkhead — изоляция ресурсов через ограничение concurrency (ADR-005).

Bulkhead-паттерн предотвращает «заливание» всего приложения при отказе
одного даунстрима: разным ресурсам выделяются независимые semaphore-пулы.
В сочетании с per-tenant rate-limiter это защищает банковскую шину от
каскадных сбоев.

Реализация на ``asyncio.Semaphore`` — лёгкая, process-local. Для
кластерной координации используется RateLimiter на Redis
(``rate_limiter.py``).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

__all__ = ("Bulkhead", "BulkheadRegistry", "BulkheadExhausted")

logger = logging.getLogger("resilience.bulkhead")


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
        except asyncio.TimeoutError as exc:
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


class BulkheadRegistry:
    """Глобальный registry Bulkhead-инстансов по имени ресурса."""

    def __init__(self) -> None:
        self._items: dict[str, Bulkhead] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self, name: str, *, max_concurrent: int = 32, wait_timeout: float = 5.0
    ) -> Bulkhead:
        async with self._lock:
            bh = self._items.get(name)
            if bh is None:
                bh = Bulkhead(
                    name=name, max_concurrent=max_concurrent, wait_timeout=wait_timeout
                )
                self._items[name] = bh
            return bh

    def list_names(self) -> list[str]:
        return sorted(self._items.keys())


# Module-level singleton.
registry = BulkheadRegistry()
