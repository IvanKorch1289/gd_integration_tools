"""BulkheadScaler — adaptive Bulkhead autoscaling (Sprint 4 Wave D, V15 R-V15-10 уровень 2).

Назначение:
    Task-level автоскалирование на основе HighWatermark/LowWatermark
    over asyncio.Semaphore-utilization. При HW (≥90% in_use) → +adjust_step
    к max_concurrent. При LW (≤30% in_use) → −adjust_step, но не ниже min.

Архитектура:
    * Не клонирует Bulkhead — пересоздаёт ``_sem`` с новой ёмкостью внутри.
    * Atomic update через asyncio.Lock внутри BulkheadRegistry.
    * Логирует структурно через structlog.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Lazy import: Bulkhead и BulkheadRegistry используются только для типов.
    # Это не создаёт runtime-зависимость core → infrastructure.
    from src.backend.infrastructure.resilience.bulkhead import (
        Bulkhead,
        BulkheadRegistry,
    )


def __getattr__(name: str):
    if not TYPE_CHECKING:
        if name in ("Bulkhead", "BulkheadRegistry"):
            from src.backend.infrastructure.resilience import bulkhead
            return getattr(bulkhead, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ("BulkheadScaler",)

_logger = logging.getLogger("core.scaling.bulkhead_scaler")


def _utilization(bulkhead: Bulkhead) -> float:
    """Оценить utilization (in_use / max_concurrent) для bulkhead.

    Используется внутренняя структура asyncio.Semaphore: ``_value`` —
    остаток свободных слотов. utilization = (max - _value) / max.

    Returns:
        Float [0.0..1.0]; 0.0 если bulkhead ещё не активирован.
    """
    sem = bulkhead._sem  # noqa: SLF001 — read-only utility, нет публичного API
    if sem is None:
        return 0.0
    remaining = sem._value  # noqa: SLF001 — asyncio internal
    in_use = bulkhead.max_concurrent - remaining
    return max(0.0, min(1.0, in_use / max(1, bulkhead.max_concurrent)))


def _resize(bulkhead: Bulkhead, new_max: int) -> None:
    """Изменить ``max_concurrent`` bulkhead с пересозданием semaphore.

    Внимание: текущие active-задачи продолжают работать; новые получат
    лимит по новому семафору.
    """
    bulkhead.max_concurrent = new_max
    bulkhead._sem = asyncio.Semaphore(new_max)  # noqa: SLF001


class BulkheadScaler:
    """Adaptive scaler для всех Bulkhead в registry.

    Args:
        registry: Глобальный :class:`BulkheadRegistry`.
        high_watermark_pct: Порог scale-up (default 0.9 = 90% utilization).
        low_watermark_pct: Порог scale-down (default 0.3 = 30%).
        adjust_step: Размер шага изменения max_concurrent (>=1).
        min_capacity: Минимум max_concurrent (защита от 0).
        max_capacity: Максимум max_concurrent.
    """

    def __init__(
        self,
        registry: BulkheadRegistry,
        *,
        high_watermark_pct: float = 0.9,
        low_watermark_pct: float = 0.3,
        adjust_step: int = 2,
        min_capacity: int = 4,
        max_capacity: int = 256,
    ) -> None:
        if not (0.0 < low_watermark_pct < high_watermark_pct <= 1.0):
            raise ValueError("0 < low_watermark < high_watermark ≤ 1.0 обязательно")
        if adjust_step < 1:
            raise ValueError("adjust_step должен быть >= 1")
        self._registry = registry
        self.high_watermark_pct = high_watermark_pct
        self.low_watermark_pct = low_watermark_pct
        self.adjust_step = adjust_step
        self.min_capacity = min_capacity
        self.max_capacity = max_capacity

    async def tick(self) -> dict[str, int]:
        """Один проход adjusting всех bulkhead.

        Returns:
            ``{bulkhead_name: new_max_concurrent}`` после tick'а.
        """
        results: dict[str, int] = {}
        names = self._registry.list_names()
        for name in names:
            bulkhead = await self._registry.get_or_create(name)
            util = _utilization(bulkhead)
            old_max = bulkhead.max_concurrent
            new_max = old_max

            if util >= self.high_watermark_pct:
                new_max = min(self.max_capacity, old_max + self.adjust_step)
            elif util <= self.low_watermark_pct:
                new_max = max(self.min_capacity, old_max - self.adjust_step)

            if new_max != old_max:
                _resize(bulkhead, new_max)
                _logger.info(
                    "BulkheadScaler '%s': util=%.2f, %d → %d",
                    name,
                    util,
                    old_max,
                    new_max,
                )
            results[name] = new_max
        return results
