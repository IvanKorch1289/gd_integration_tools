"""Retry budget — защита от retry storm.

Sprint 1 V16 Single-Entry: единая реализация ``RetryBudget``, объединяющая
бывшие классы из ``core/resilience.py`` (глобальный budget) и
``infrastructure/resilience/retry_budget.py`` (per-resource).

Идея: не более ``ratio`` (по умолчанию 20 %) запросов в скользящем окне
могут быть retries. При превышении — быстрые fail.

Реализация использует :class:`collections.deque` для O(1) добавления и
тримминга по левому краю.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("RetryBudget", "RetryBudgetExhausted", "get_retry_budget")

logger = get_logger("resilience.retry_budget")


class RetryBudgetExhausted(Exception):
    """Бюджет retry исчерпан — retry отклонён."""

    def __init__(self, name: str = "global") -> None:
        super().__init__(f"Retry budget exhausted: {name}")
        self.name = name


class RetryBudget:
    """Единый retry-budget — поддерживает global и per-resource режимы.

    Args:
        name: Имя ресурса (для логов/метрик). Default: ``"global"``.
        window_seconds: Скользящее окно для подсчёта.
        ratio: Доля retry от total (например, ``0.2`` = 20 %).
        min_retries_per_sec: Гарантированный минимум (anti-starvation),
            обеспечивает что даже при отсутствии трафика хотя бы N retry
            в секунду доступны. ``0.0`` отключает.
    """

    def __init__(
        self,
        name: str = "global",
        *,
        window_seconds: float = 60.0,
        ratio: float = 0.2,
        min_retries_per_sec: float = 0.0,
    ) -> None:
        self.name = name
        self._window = window_seconds
        self._ratio = ratio
        self._min_retries_per_sec = min_retries_per_sec
        self._total: deque[float] = deque()
        self._retries: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def record_request(self) -> None:
        """Регистрирует исходный запрос (не retry)."""
        async with self._lock:
            self._total.append(time.monotonic())
            self._trim()

    # Обратная совместимость с infrastructure-шной семантикой "attempt".
    record_attempt = record_request

    async def try_retry(self) -> bool:
        """Возвращает ``True``, если retry разрешён бюджетом.

        Алгоритм: max(min_retries_per_sec * window, total * ratio).
        Если фактических retry уже больше — отказ.
        """
        now = time.monotonic()
        async with self._lock:
            self._trim()
            total = len(self._total)
            retries = len(self._retries)
            allowed = max(self._min_retries_per_sec * self._window, total * self._ratio)
            if retries >= allowed:
                logger.warning(
                    "RetryBudget '%s' exhausted: %d/%g retries in %gs",
                    self.name,
                    retries,
                    allowed,
                    self._window,
                )
                return False
            self._retries.append(now)
            return True

    def _trim(self) -> None:
        """Удаляет события вне окна (O(1) на элемент с левого края)."""
        cutoff = time.monotonic() - self._window
        while self._total and self._total[0] < cutoff:
            self._total.popleft()
        while self._retries and self._retries[0] < cutoff:
            self._retries.popleft()

    def stats(self) -> dict[str, Any]:
        """Get current retry budget statistics.

        Returns:
            Dict with name, total_in_window, retries_in_window, ratio, max_ratio.
        """
        return {
            "name": self.name,
            "total_in_window": len(self._total),
            "retries_in_window": len(self._retries),
            "ratio": len(self._retries) / max(len(self._total), 1),
            "max_ratio": self._ratio,
        }


_retry_budget: RetryBudget | None = None


def get_retry_budget() -> RetryBudget:
    """Singleton-аксессор для глобального RetryBudget."""
    global _retry_budget
    if _retry_budget is None:
        _retry_budget = RetryBudget(name="global")
    return _retry_budget
