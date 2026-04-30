"""Protocol источника времени для DSL-процессоров (W14 pre-step).

Wall-clock и monotonic-часы абстрагированы для:

* детерминированного тестирования windowed-процессоров без `monkeypatch`;
* возможности замены backend (например, MockClock в e2e-сценариях);
* корректной классификации watermarks (W14.3).

Реализации — в ``src/core/clock.py``: ``RealClock`` (production)
и ``FakeClock`` (для тестов).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ("Clock",)


@runtime_checkable
class Clock(Protocol):
    """Источник времени.

    Methods:
        monotonic: Монотонно растущее время в секундах. Не зависит
            от изменений wall-clock. Используется для измерения интервалов.
        time: Wall-clock время (Unix epoch seconds). Может откатываться
            при ручной коррекции системных часов или NTP.
    """

    def monotonic(self) -> float: ...

    def time(self) -> float: ...
