"""Retry budget — глобальная защита от retry storm.

Идея: не более ``max_ratio`` (по умолчанию 20%) запросов в окне могут
быть retries. При превышении — быстрые fail.

Реализация использует :mod:`collections.deque` с фиксированной ёмкостью
для эффективного скользящего окна (O(1) добавление, без list-comprehension
на каждом вызове). Для настоящих ретраев вокруг HTTP-клиента рекомендуется
использовать ``tenacity.AsyncRetrying`` поверх этого бюджета.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

__all__ = ("RetryBudget", "get_retry_budget")


class RetryBudget:
    """Глобальный бюджет ретраев — защита от retry storm."""

    def __init__(self, window_seconds: int = 60, max_ratio: float = 0.2) -> None:
        self._window = window_seconds
        self._max_ratio = max_ratio
        self._total: deque[float] = deque()
        self._retries: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def record_request(self) -> None:
        async with self._lock:
            self._total.append(time.monotonic())
            self._trim()

    async def try_retry(self) -> bool:
        """Возвращает True если retry разрешён."""
        async with self._lock:
            self._trim()
            total = len(self._total)
            retries = len(self._retries)
            if total == 0:
                return True
            ratio = retries / total
            if ratio >= self._max_ratio:
                return False
            self._retries.append(time.monotonic())
            return True

    def _trim(self) -> None:
        """Удаляет события вне окна из deque (O(1) на элемент с левого края)."""
        cutoff = time.monotonic() - self._window
        while self._total and self._total[0] < cutoff:
            self._total.popleft()
        while self._retries and self._retries[0] < cutoff:
            self._retries.popleft()

    def stats(self) -> dict[str, Any]:
        return {
            "total_in_window": len(self._total),
            "retries_in_window": len(self._retries),
            "ratio": len(self._retries) / max(len(self._total), 1),
            "max_ratio": self._max_ratio,
        }


_retry_budget: RetryBudget | None = None


def get_retry_budget() -> RetryBudget:
    """Singleton-аксессор для глобального RetryBudget."""
    global _retry_budget
    if _retry_budget is None:
        _retry_budget = RetryBudget()
    return _retry_budget
