"""Реализации Protocol :class:`src.core.interfaces.clock.Clock` (W14 pre-step).

* :class:`RealClock` — production-обёртка над модулем ``time``.
* :class:`FakeClock` — controllable источник для unit-тестов и chaos-сценариев.
"""

from __future__ import annotations

import time as _time

from src.backend.core.interfaces.clock import Clock

__all__ = ("RealClock", "FakeClock")


class RealClock:
    """Production-источник времени: stdlib ``time``.

    Делегирует ``time.monotonic`` и ``time.time`` без модификаций.
    """

    def monotonic(self) -> float:
        return _time.monotonic()

    def time(self) -> float:
        return _time.time()


class FakeClock:
    """Controllable источник времени для тестов.

    Args:
        monotonic_start: Начальное значение монотонного счётчика.
        wall_start: Начальное значение wall-clock (Unix epoch seconds).
    """

    def __init__(
        self, *, monotonic_start: float = 0.0, wall_start: float = 0.0
    ) -> None:
        self._mono = monotonic_start
        self._wall = wall_start

    def monotonic(self) -> float:
        return self._mono

    def time(self) -> float:
        return self._wall

    def advance(self, seconds: float) -> None:
        """Продвинуть оба счётчика на ``seconds`` (может быть отрицательным
        только для wall-clock, monotonic не откатывается).

        Args:
            seconds: Сколько секунд добавить к текущему времени.

        Raises:
            ValueError: При отрицательном ``seconds`` для monotonic.
        """
        if seconds < 0:
            raise ValueError("monotonic не может уменьшаться")
        self._mono += seconds
        self._wall += seconds

    def set_wall(self, wall: float) -> None:
        """Жёстко установить wall-clock (имитация NTP-коррекции)."""
        self._wall = wall


# Smoke-проверка соответствия Protocol на этапе импорта (mypy + runtime).
_real: Clock = RealClock()
_fake: Clock = FakeClock()
