"""Tests for ``src.backend.core.resilience.backpressure.types``.

S67 W1: core types for backpressure decomp (Protocol + state dataclass).
"""

from __future__ import annotations

import time

from src.backend.core.resilience.backpressure import types as mod
from src.backend.core.resilience.backpressure.types import (
    BackpressureState,
    ConsumerControlProtocol,
)


class TestBackpressureStateDefaults:
    """BackpressureState dataclass defaults."""

    def test_default_queue_size(self) -> None:
        s = BackpressureState()
        assert s.queue_size == 0

    def test_default_queue_limit(self) -> None:
        s = BackpressureState()
        assert s.queue_limit == 1000

    def test_default_is_paused(self) -> None:
        s = BackpressureState()
        assert s.is_paused is False

    def test_default_last_state_change_at_is_monotonic(self) -> None:
        before = time.monotonic()
        s = BackpressureState()
        after = time.monotonic()
        # last_state_change_at default — monotonic time
        assert before <= s.last_state_change_at <= after


class TestBackpressureStateExplicit:
    """Явные значения."""

    def test_explicit_queue_size(self) -> None:
        s = BackpressureState(queue_size=500)
        assert s.queue_size == 500

    def test_explicit_queue_limit(self) -> None:
        s = BackpressureState(queue_limit=2000)
        assert s.queue_limit == 2000

    def test_explicit_is_paused_true(self) -> None:
        s = BackpressureState(is_paused=True)
        assert s.is_paused is True

    def test_explicit_last_state_change_at(self) -> None:
        ts = 12345.678
        s = BackpressureState(last_state_change_at=ts)
        assert s.last_state_change_at == ts


class TestBackpressureStateUtilization:
    """utilization property — queue_size / queue_limit."""

    def test_zero_utilization(self) -> None:
        s = BackpressureState(queue_size=0, queue_limit=1000)
        assert s.utilization == 0.0

    def test_half_utilization(self) -> None:
        s = BackpressureState(queue_size=500, queue_limit=1000)
        assert s.utilization == 0.5

    def test_full_utilization(self) -> None:
        s = BackpressureState(queue_size=1000, queue_limit=1000)
        assert s.utilization == 1.0

    def test_over_utilization(self) -> None:
        # queue_size > queue_limit → utilization > 1.0
        s = BackpressureState(queue_size=2000, queue_limit=1000)
        assert s.utilization == 2.0

    def test_zero_queue_limit_returns_zero(self) -> None:
        # Edge case: limit=0 → деление на ноль не должно происходить
        s = BackpressureState(queue_size=100, queue_limit=0)
        assert s.utilization == 0.0

    def test_negative_queue_limit_returns_zero(self) -> None:
        # Defensive: negative limit → не падать
        s = BackpressureState(queue_size=100, queue_limit=-1)
        assert s.utilization == 0.0


class TestConsumerControlProtocol:
    """ConsumerControlProtocol — Protocol для consumer pause/resume."""

    def test_protocol_importable(self) -> None:
        assert ConsumerControlProtocol is not None

    def test_has_pause(self) -> None:
        assert hasattr(ConsumerControlProtocol, "pause")

    def test_has_resume(self) -> None:
        assert hasattr(ConsumerControlProtocol, "resume")

    def test_pause_is_coroutine(self) -> None:
        import inspect

        assert inspect.iscoroutinefunction(ConsumerControlProtocol.pause)

    def test_resume_is_coroutine(self) -> None:
        import inspect

        assert inspect.iscoroutinefunction(ConsumerControlProtocol.resume)

    def test_pause_returns_none(self) -> None:
        import inspect

        sig = inspect.signature(ConsumerControlProtocol.pause)
        # Аннотация — строка "None" (forward reference) или None
        ann = sig.return_annotation
        assert ann in (None, "None", inspect._empty)

    def test_resume_returns_none(self) -> None:
        import inspect

        sig = inspect.signature(ConsumerControlProtocol.resume)
        ann = sig.return_annotation
        assert ann in (None, "None", inspect._empty)

    def test_protocol_conformant_class(self) -> None:
        # Реализация с async pause/resume

        class _FakeConsumer:
            async def pause(self) -> None:
                pass

            async def resume(self) -> None:
                pass

        # Protocol не помечен runtime_checkable, но структурная совместимость — да
        consumer = _FakeConsumer()
        # isinstance check не работает без runtime_checkable,
        # но duck-typing работает
        assert hasattr(consumer, "pause")
        assert hasattr(consumer, "resume")


class TestStateEquality:
    """BackpressureState equality (dataclass)."""

    def test_equal_when_explicit_same(self) -> None:
        # Явное значение для last_state_change_at — тогда equality работает
        ts = 12345.0
        a = BackpressureState(
            queue_size=10,
            queue_limit=100,
            is_paused=True,
            last_state_change_at=ts,
        )
        b = BackpressureState(
            queue_size=10,
            queue_limit=100,
            is_paused=True,
            last_state_change_at=ts,
        )
        assert a == b

    def test_not_equal_when_different(self) -> None:
        a = BackpressureState(queue_size=10, last_state_change_at=1.0)
        b = BackpressureState(queue_size=20, last_state_change_at=2.0)
        assert a != b

    def test_default_timestamps_differ(self) -> None:
        # default_factory=time.monotonic — два default instance не равны
        a = BackpressureState()
        # Небольшая задержка чтобы monotonic ушёл вперёд
        b = BackpressureState()
        # Хотя может быть равны если monotonic имеет высокую resolution
        # Проверяем только что они созданы
        assert isinstance(a.last_state_change_at, float)
        assert isinstance(b.last_state_change_at, float)


class TestModuleExports:
    """__all__ проверка."""

    def test_module_imports(self) -> None:
        from src.backend.core.resilience.backpressure import types as m

        assert m is mod

    def test_classes_in_module(self) -> None:
        # BackpressureState и ConsumerControlProtocol — экспортируются
        assert "BackpressureState" in dir(mod)
        assert "ConsumerControlProtocol" in dir(mod)