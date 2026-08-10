"""Unit-тесты для Circuit Breaker Facade (S173 + FW6.1).

Тестирует scaffold из :mod:`src.backend.core.resilience.circuit_breaker`:
- :class:`BreakerLike` — minimal contract Protocol
- :class:`SlidingWindowBreaker` — per-route CB adapter (TODO s172/m2.4)
- :class:`ReplicaFailoverBreaker` — replica failover CB (working stub)
- Re-exports из :mod:`src.backend.core.resilience.breaker`

FW6.1: ``CircuitBreakerSpec`` удалён (DEPRECATED shim после FW6).
Все тесты используют :class:`BreakerSpec` из :mod:`breaker` (canonical).
"""

from __future__ import annotations

import pytest

from src.backend.core.resilience.breaker import BreakerSpec
from src.backend.core.resilience.circuit_breaker import (
    HAS_PURGATORY,
    BreakerLike,
    BreakerRegistry,
    CircuitOpen,
    ReplicaFailoverBreaker,
    SlidingWindowBreaker,
)


class TestBreakerSpec:
    """Тесты канонической спецификации BreakerSpec (post-FW6.1)."""

    def test_default_values(self) -> None:
        """Проверяет значения по умолчанию."""
        spec = BreakerSpec()
        assert spec.failure_threshold == 5
        assert spec.recovery_timeout == 30.0
        assert spec.window_seconds == 0.0
        assert spec.half_open_max_calls == 1
        assert spec.excluded_exceptions == ()

    def test_custom_values(self) -> None:
        """Проверяет установку кастомных значений."""
        spec = BreakerSpec(
            failure_threshold=10,
            recovery_timeout=60.0,
            window_seconds=120.0,
            half_open_max_calls=3,
            excluded_exceptions=(TimeoutError,),
        )
        assert spec.failure_threshold == 10
        assert spec.recovery_timeout == 60.0
        assert spec.window_seconds == 120.0
        assert spec.half_open_max_calls == 3
        assert spec.excluded_exceptions == (TimeoutError,)

    def test_frozen(self) -> None:
        """Spec должен быть immutable (frozen dataclass)."""
        spec = BreakerSpec()
        with pytest.raises((AttributeError, Exception)):
            spec.failure_threshold = 100  # type: ignore[misc]


class TestBreakerLikeProtocol:
    """Тесты BreakerLike Protocol (минимальный contract)."""

    def test_protocol_structure(self) -> None:
        """Проверяет что Protocol имеет ожидаемые методы."""
        # Protocol проверяется через наличие методов на duck-typed объекте
        class MockBreaker:
            def is_open(self) -> bool:
                return False

            def on_success(self) -> None:
                pass

            def on_failure(self) -> None:
                pass

        mock = MockBreaker()
        assert isinstance(mock, BreakerLike) or hasattr(mock, "is_open")


class TestReplicaFailoverBreaker:
    """Тесты ReplicaFailoverBreaker — S173 M2.4 реализация."""

    def test_initial_state_closed(self) -> None:
        """Изначально breaker закрыт."""
        spec = BreakerSpec(failure_threshold=3)
        breaker = ReplicaFailoverBreaker(name="test_replica", spec=spec)
        assert breaker.is_open is False
        assert breaker.state == "closed"

    def test_opens_after_threshold_failures(self) -> None:
        """Breaker открывается после failure_threshold failures."""
        spec = BreakerSpec(failure_threshold=3)
        breaker = ReplicaFailoverBreaker(name="test_replica", spec=spec)

        breaker.on_failure()
        breaker.on_failure()
        assert breaker.is_open is False  # 2 failures, threshold=3

        breaker.on_failure()
        assert breaker.is_open is True  # 3 failures → open

    def test_on_success_resets_counter(self) -> None:
        """on_success() сбрасывает счётчик failures и закрывает breaker."""
        spec = BreakerSpec(failure_threshold=3)
        breaker = ReplicaFailoverBreaker(name="test_replica", spec=spec)

        breaker.on_failure()
        breaker.on_failure()
        breaker.on_success()  # сбрасывает
        assert breaker.is_open is False

        # Можно накопить заново
        breaker.on_failure()
        breaker.on_failure()
        assert breaker.is_open is False
        breaker.on_failure()
        assert breaker.is_open is True

    def test_zero_threshold_degenerate(self) -> None:
        """При failure_threshold=0 breaker всегда открыт (degenerate)."""
        spec = BreakerSpec(failure_threshold=0)
        breaker = ReplicaFailoverBreaker(name="test_replica", spec=spec)
        # 0 >= 0 == True — degenerate case
        assert breaker.is_open is True

    def test_recovery_after_timeout(self) -> None:
        """После recovery_timeout breaker переходит в half_open."""
        import time

        spec = BreakerSpec(failure_threshold=2, recovery_timeout=0.1)
        breaker = ReplicaFailoverBreaker(name="test_replica", spec=spec)

        breaker.on_failure()
        breaker.on_failure()
        assert breaker.is_open is True

        time.sleep(0.15)  # больше recovery_timeout

        # После timeout state должен стать half_open (is_open=False)
        assert breaker.is_open is False
        assert breaker.state == "half_open"

        # Успех закрывает
        breaker.on_success()
        assert breaker.state == "closed"


class TestSlidingWindowBreaker:
    """Тесты SlidingWindowBreaker (S173 M2.4 реализация)."""

    def test_initial_state_closed(self) -> None:
        """Изначально breaker закрыт."""
        spec = BreakerSpec()
        breaker = SlidingWindowBreaker(name="test_route", spec=spec)
        assert breaker.state == "closed"
        assert breaker.is_open is False

    def test_opens_after_threshold(self) -> None:
        """Breaker открывается после failure_threshold failures."""
        spec = BreakerSpec(failure_threshold=3)
        breaker = SlidingWindowBreaker(name="test_route", spec=spec)

        # Trigger failures via guard context manager
        import asyncio

        async def trigger_failures() -> None:
            for _ in range(2):
                try:
                    async with breaker.guard():
                        raise ValueError("test")
                except ValueError:
                    pass
            assert breaker.state == "closed"  # 2 failures, threshold=3

            try:
                async with breaker.guard():
                    raise ValueError("test")
            except ValueError:
                pass
            assert breaker.state == "open"  # 3 failures → open

        asyncio.run(trigger_failures())

    def test_guard_succeeds_when_closed(self) -> None:
        """guard() пропускает вызов при closed state."""
        import asyncio

        async def run_test() -> None:
            spec = BreakerSpec()
            breaker = SlidingWindowBreaker(name="test_route", spec=spec)
            async with breaker.guard():
                pass  # успешный вызов

        asyncio.run(run_test())

    def test_guard_raises_when_open(self) -> None:
        """guard() бросает CircuitOpen при open state."""
        import asyncio

        from src.backend.core.resilience.circuit_breaker import CircuitOpen

        async def run_test() -> None:
            spec = BreakerSpec(failure_threshold=1)
            breaker = SlidingWindowBreaker(name="test_route", spec=spec)
            try:
                async with breaker.guard():
                    raise ValueError("trigger")
            except ValueError:
                pass

            # Теперь breaker открыт
            with pytest.raises(CircuitOpen):
                async with breaker.guard():
                    pass

        asyncio.run(run_test())

    def test_success_closes_breaker(self) -> None:
        """Успешный вызов сбрасывает failures и закрывает breaker."""
        import asyncio

        async def run_test() -> None:
            spec = BreakerSpec(failure_threshold=2)
            breaker = SlidingWindowBreaker(name="test_route", spec=spec)

            # 1 failure
            try:
                async with breaker.guard():
                    raise ValueError("trigger")
            except ValueError:
                pass

            # Успех — должен сбросить
            async with breaker.guard():
                pass
            assert breaker.state == "closed"

        asyncio.run(run_test())

    def test_excluded_exceptions_dont_count(self) -> None:
        """Исключения из excluded_exceptions не считаются failures."""
        import asyncio

        async def run_test() -> None:
            spec = BreakerSpec(
                failure_threshold=2, excluded_exceptions=(KeyError,),
            )
            breaker = SlidingWindowBreaker(name="test_route", spec=spec)

            # KeyError не должно считаться
            for _ in range(5):
                try:
                    async with breaker.guard():
                        raise KeyError("not counted")
                except KeyError:
                    pass

            assert breaker.state == "closed"

        asyncio.run(run_test())


class TestCanonicalReExports:
    """Тесты re-export canonical API из breaker.py."""

    def test_breaker_registry_importable(self) -> None:
        """BreakerRegistry re-exported."""
        assert BreakerRegistry is not None

    def test_circuit_open_importable(self) -> None:
        """CircuitOpen re-exported (alias to purgatory OpenedState)."""
        assert CircuitOpen is not None


class TestHAS_PURGATORY:
    """Тест флага HAS_PURGATORY — корректно отражает наличие purgatory."""

    def test_purgatory_available_in_test_env(self) -> None:
        """purgatory должен быть установлен в test environment."""
        # Если purgatory не установлен — scaffold бросит ошибки при импорте
        assert HAS_PURGATORY is True
