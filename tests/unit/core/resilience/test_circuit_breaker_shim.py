"""FW6: тесты CircuitBreakerSpec deprecation shim.

Проверяют:
- CircuitBreakerSpec(...) всё ещё работает (backward-compat)
- DeprecationWarning emitted
- isinstance(spec, BreakerSpec) — True (type-merge)
- Все поля доступны (включая добавленные в FW6: window_seconds,
  half_open_max_calls, excluded_exceptions)
"""
from __future__ import annotations

import pytest

# ruff: noqa: S101


def test_circuit_breaker_spec_emits_deprecation_warning() -> None:
    """Импорт + инстанциация → DeprecationWarning."""
    import warnings

    from src.backend.core.resilience.circuit_breaker import CircuitBreakerSpec

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        CircuitBreakerSpec(failure_threshold=3, window_seconds=60)
    assert any(
        issubclass(x.category, DeprecationWarning)
        and "DEPRECATED" in str(x.message)
        for x in w
    ), f"expected DeprecationWarning, got {[str(x.message) for x in w]}"


def test_circuit_breaker_spec_is_breaker_spec() -> None:
    """Shim возвращает instance :class:`BreakerSpec` (post-FW6 расширен)."""
    import warnings

    from src.backend.core.resilience.breaker import BreakerSpec
    from src.backend.core.resilience.circuit_breaker import CircuitBreakerSpec

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        spec = CircuitBreakerSpec(failure_threshold=3, window_seconds=60)
    assert isinstance(spec, BreakerSpec)
    assert spec.failure_threshold == 3
    assert spec.window_seconds == 60


def test_circuit_breaker_spec_default_values_match() -> None:
    """Defaults CircuitBreakerSpec == BreakerSpec (FW6 unification)."""
    import warnings

    from src.backend.core.resilience.breaker import BreakerSpec
    from src.backend.core.resilience.circuit_breaker import CircuitBreakerSpec

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        old_spec = CircuitBreakerSpec()
        new_spec = BreakerSpec()
    # Все поля должны совпадать.
    for f in (
        "name", "failure_threshold", "recovery_timeout",
        "window_seconds", "half_open_max_calls", "excluded_exceptions",
    ):
        assert getattr(old_spec, f) == getattr(new_spec, f), (
            f"field {f!r} differs: old={getattr(old_spec, f)!r} "
            f"new={getattr(new_spec, f)!r}"
        )


def test_breaker_spec_has_new_fields() -> None:
    """BreakerSpec (post-FW6) имеет 3 новых optional-поля."""
    from src.backend.core.resilience.breaker import BreakerSpec

    spec = BreakerSpec(window_seconds=30.0, half_open_max_calls=2)
    assert spec.window_seconds == 30.0
    assert spec.half_open_max_calls == 2
    assert spec.excluded_exceptions == ()


def test_breaker_spec_excluded_exceptions() -> None:
    """excluded_exceptions принимает tuple типов."""
    from src.backend.core.resilience.breaker import BreakerSpec

    spec = BreakerSpec(
        excluded_exceptions=(ValueError, KeyError),
    )
    assert spec.excluded_exceptions == (ValueError, KeyError)


def test_circuit_breaker_spec_isinstance_breaker_spec() -> None:
    """Прямая проверка isinstance — критично для callers."""
    import warnings

    from src.backend.core.resilience.breaker import BreakerSpec
    from src.backend.core.resilience.circuit_breaker import CircuitBreakerSpec

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        spec = CircuitBreakerSpec(
            name="test",
            failure_threshold=5,
            window_seconds=60.0,
        )
    # Это контракт, который важен для ``SlidingWindowBreaker(spec=...)``.
    assert isinstance(spec, BreakerSpec)
    assert spec.name == "test"
    assert spec.failure_threshold == 5
    assert spec.window_seconds == 60.0
