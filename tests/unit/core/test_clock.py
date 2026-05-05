"""Юнит-тесты Clock Protocol (W14 pre-step C.0).

Покрывает:

* контракт Protocol (RealClock и FakeClock — instances Clock);
* монотонность FakeClock.monotonic;
* возможность сдвига wall-clock через set_wall;
* отказ FakeClock.advance при отрицательном значении.
"""

# ruff: noqa: S101

from __future__ import annotations

import time as _time

import pytest

from src.backend.core.clock import FakeClock, RealClock
from src.backend.core.interfaces.clock import Clock


class TestProtocolConformance:
    def test_real_clock_is_clock(self) -> None:
        assert isinstance(RealClock(), Clock)

    def test_fake_clock_is_clock(self) -> None:
        assert isinstance(FakeClock(), Clock)


class TestRealClock:
    def test_monotonic_close_to_stdlib(self) -> None:
        rc = RealClock()
        a = rc.monotonic()
        b = _time.monotonic()
        # Обе функции из time модуля; разрыв << 0.5s.
        assert abs(a - b) < 0.5

    def test_time_close_to_stdlib(self) -> None:
        rc = RealClock()
        assert abs(rc.time() - _time.time()) < 1.0


class TestFakeClock:
    def test_starts_at_zero_by_default(self) -> None:
        fc = FakeClock()
        assert fc.monotonic() == 0.0
        assert fc.time() == 0.0

    def test_custom_start(self) -> None:
        fc = FakeClock(monotonic_start=100.0, wall_start=1_700_000_000.0)
        assert fc.monotonic() == 100.0
        assert fc.time() == 1_700_000_000.0

    def test_advance_moves_both(self) -> None:
        fc = FakeClock(monotonic_start=10.0, wall_start=1000.0)
        fc.advance(5.5)
        assert fc.monotonic() == 15.5
        assert fc.time() == 1005.5

    def test_advance_negative_raises(self) -> None:
        fc = FakeClock()
        with pytest.raises(ValueError, match="не может уменьшаться"):
            fc.advance(-1.0)

    def test_set_wall_does_not_affect_monotonic(self) -> None:
        fc = FakeClock(monotonic_start=10.0)
        fc.set_wall(9999.0)
        assert fc.monotonic() == 10.0
        assert fc.time() == 9999.0
