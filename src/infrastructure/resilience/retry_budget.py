"""Retry budget — ограничение на процент повторов в единицу времени (ADR-005).

При отказе даунстрима простой retry-цикл **усиливает** нагрузку: клиент
повторяет запросы в разгар инцидента и ускоряет коллапс. Retry budget
ограничивает долю запросов, которые могут быть повторены — например,
«не более 10 % от трафика за последнюю минуту».

Алгоритм — token bucket по истории запросов (ролящее окно).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

__all__ = ("RetryBudget", "RetryBudgetExhausted")

logger = logging.getLogger("resilience.retry_budget")


class RetryBudgetExhausted(Exception):
    """Retry budget исчерпан — retry отклонён."""


@dataclass(slots=True)
class RetryBudget:
    """Ограничивает число retry как % от суммарных запросов в окне.

    Attrs:
        name: Имя ресурса (для логов/метрик).
        min_retries_per_sec: Гарантированный минимум (anti-starvation).
        ratio: Доля от успешных вызовов, доступная как retry (``0.1`` = 10 %).
        window_seconds: Скользящее окно для подсчёта.
    """

    name: str
    min_retries_per_sec: float = 1.0
    ratio: float = 0.1
    window_seconds: float = 60.0
    _attempts: list[float] = None  # type: ignore[assignment]
    _retries: list[float] = None  # type: ignore[assignment]
    _lock: asyncio.Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._attempts = []
        self._retries = []
        self._lock = asyncio.Lock()

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self._attempts = [t for t in self._attempts if t >= cutoff]
        self._retries = [t for t in self._retries if t >= cutoff]

    async def record_attempt(self) -> None:
        now = time.monotonic()
        async with self._lock:
            self._attempts.append(now)
            self._trim(now)

    async def try_retry(self) -> bool:
        """Возвращает True, если retry разрешён (бюджет не исчерпан)."""
        now = time.monotonic()
        async with self._lock:
            self._trim(now)
            attempts = len(self._attempts)
            retries = len(self._retries)
            allowed = max(
                self.min_retries_per_sec * self.window_seconds, attempts * self.ratio
            )
            if retries >= allowed:
                logger.warning(
                    "RetryBudget '%s' exhausted: %d/%g retries in %gs",
                    self.name,
                    retries,
                    allowed,
                    self.window_seconds,
                )
                return False
            self._retries.append(now)
            return True
