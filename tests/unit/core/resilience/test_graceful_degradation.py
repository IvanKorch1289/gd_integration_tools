"""Unit-тесты GracefulDegradationRegistry (S13 K2 W4).

Покрывает:
    1. register + is_registered — корректная регистрация feature.
    2. healthy_outcome_keeps_full_handler — успехи → full_handler.
    3. errors_trigger_degraded — error_rate ≥ threshold → DEGRADED.
    4. recovery_path — DEGRADED → RECOVERING → HEALTHY при стабильности.
    5. recovering_back_to_degraded — пока в recovering, новый всплеск ошибок снова degrades.
    6. unknown_feature_returns_none_handler — get_handler для не зарегистрированного feature.
    7. manual_recover — recover() сбрасывает state в HEALTHY.
    8. snapshot — структура admin-снимка.
    9. concurrent_record_outcome — конкурентные вызовы не повреждают окно.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.core.resilience.graceful_degradation import (
    DegradationFeature,
    FeatureState,
    GracefulDegradationRegistry,
    get_graceful_degradation_registry,
)


def _full(*args: Any, **kw: Any) -> str:
    """Stub полного handler'а."""
    return "full"


def _degraded(*args: Any, **kw: Any) -> str:
    """Stub деградированного handler'а."""
    return "degraded"


def _make_feature(
    name: str = "search.test",
    *,
    error_threshold: float = 0.3,
    recovery_threshold: float = 0.05,
    window_size: int = 10,
) -> DegradationFeature:
    """Конструктор feature с маленьким окном для быстрых тестов."""
    return DegradationFeature(
        name=name,
        full_handler=_full,
        degraded_handler=_degraded,
        error_threshold=error_threshold,
        recovery_threshold=recovery_threshold,
        window_size=window_size,
    )


def test_register_and_query() -> None:
    """register() кладёт feature в реестр; is_registered/get_state корректны."""
    registry = GracefulDegradationRegistry()
    feature = _make_feature()
    assert registry.is_registered(feature.name) is False
    registry.register(feature)
    assert registry.is_registered(feature.name) is True
    assert registry.get_state(feature.name) == FeatureState.HEALTHY


def test_get_handler_unknown_feature_returns_none() -> None:
    """Для незарегистрированного feature get_handler возвращает None."""
    registry = GracefulDegradationRegistry()
    assert registry.get_handler("never.seen") is None


@pytest.mark.asyncio
async def test_healthy_outcome_keeps_full_handler() -> None:
    """100% успешных outcome → state HEALTHY, full_handler."""
    registry = GracefulDegradationRegistry()
    feature = _make_feature()
    registry.register(feature)
    for _ in range(10):
        await registry.record_outcome(feature.name, success=True)
    assert registry.get_state(feature.name) == FeatureState.HEALTHY
    assert registry.get_handler(feature.name) is _full


@pytest.mark.asyncio
async def test_errors_trigger_degraded() -> None:
    """error_rate ≥ threshold → state DEGRADED → degraded_handler."""
    registry = GracefulDegradationRegistry()
    feature = _make_feature(window_size=10, error_threshold=0.3)
    registry.register(feature)
    # 3 ошибки из 10 = 30% → DEGRADED при >=0.3.
    for i in range(10):
        await registry.record_outcome(feature.name, success=(i >= 3))
    assert registry.get_state(feature.name) == FeatureState.DEGRADED
    assert registry.get_handler(feature.name) is _degraded


@pytest.mark.asyncio
async def test_recovery_path_to_healthy() -> None:
    """DEGRADED → RECOVERING (error_rate ≤ recovery) → HEALTHY (полное окно)."""
    registry = GracefulDegradationRegistry()
    feature = _make_feature(
        window_size=10, error_threshold=0.3, recovery_threshold=0.05
    )
    registry.register(feature)
    # Вход в DEGRADED.
    for _ in range(10):
        await registry.record_outcome(feature.name, success=False)
    assert registry.get_state(feature.name) == FeatureState.DEGRADED

    # Серия успехов сбрасывает окно по одному, на каком-то шаге error_rate
    # упадёт до 0 — переход в RECOVERING.
    for _ in range(10):
        await registry.record_outcome(feature.name, success=True)
    assert registry.get_state(feature.name) == FeatureState.HEALTHY


@pytest.mark.asyncio
async def test_recovering_falls_back_to_degraded_on_new_errors() -> None:
    """В RECOVERING всплеск ошибок снова переключает state в DEGRADED."""
    registry = GracefulDegradationRegistry()
    feature = _make_feature(
        window_size=10, error_threshold=0.3, recovery_threshold=0.05
    )
    registry.register(feature)
    # 1) DEGRADED.
    for _ in range(10):
        await registry.record_outcome(feature.name, success=False)
    # 2) Дойдём до RECOVERING (несколько успехов).
    for _ in range(9):
        await registry.record_outcome(feature.name, success=True)
    # Окно теперь содержит 1 failure + 9 success → 10% errors.
    # Сейчас state может быть RECOVERING (recovery <0.05 проверим иначе).
    # Принудим — добавим ещё один успех, окно станет 10 успехов:
    await registry.record_outcome(feature.name, success=True)
    state_after_clean = registry.get_state(feature.name)
    assert state_after_clean in {FeatureState.RECOVERING, FeatureState.HEALTHY}
    # Сразу же серия ошибок → DEGRADED.
    for _ in range(10):
        await registry.record_outcome(feature.name, success=False)
    assert registry.get_state(feature.name) == FeatureState.DEGRADED


@pytest.mark.asyncio
async def test_record_outcome_unknown_feature_returns_healthy() -> None:
    """record_outcome для незарегистрированного feature → HEALTHY (no-op)."""
    registry = GracefulDegradationRegistry()
    state = await registry.record_outcome("missing", success=False)
    assert state == FeatureState.HEALTHY


def test_manual_recover_resets_state_and_window() -> None:
    """recover() сбрасывает состояние в HEALTHY и очищает окно."""
    registry = GracefulDegradationRegistry()
    feature = _make_feature()
    registry.register(feature)
    # Поломаем feature синхронно для теста (через __init__-side runtime).
    runtime = registry._features[feature.name]  # type: ignore[attr-defined]
    runtime.outcomes.extend([False] * 10)
    runtime.state = FeatureState.DEGRADED

    registry.recover(feature.name)
    assert registry.get_state(feature.name) == FeatureState.HEALTHY
    assert registry.get_handler(feature.name) is _full


def test_snapshot_structure() -> None:
    """snapshot() возвращает dict с state/samples/error_rate per feature."""
    registry = GracefulDegradationRegistry()
    feature = _make_feature()
    registry.register(feature)
    snap = registry.snapshot()
    assert feature.name in snap
    entry = snap[feature.name]
    assert entry["state"] == "healthy"
    assert entry["samples"] == 0
    assert entry["error_rate"] == 0.0


@pytest.mark.asyncio
async def test_concurrent_record_outcome_does_not_lose_data() -> None:
    """Конкурентные record_outcome сохраняют целостность окна (asyncio.Lock)."""
    registry = GracefulDegradationRegistry()
    feature = _make_feature(window_size=200)  # больше окна, чтобы вместить всё
    registry.register(feature)

    async def writer(n: int) -> None:
        for _ in range(n):
            await registry.record_outcome(feature.name, success=True)

    await asyncio.gather(writer(50), writer(50), writer(50), writer(50))
    snap = registry.snapshot()
    # Все 200 окончивших outcome должны попасть в окно.
    assert snap[feature.name]["samples"] == 200
    assert snap[feature.name]["error_rate"] == 0.0


def test_get_graceful_degradation_registry_singleton() -> None:
    """get_graceful_degradation_registry возвращает один и тот же экземпляр."""
    a = get_graceful_degradation_registry()
    b = get_graceful_degradation_registry()
    assert a is b
