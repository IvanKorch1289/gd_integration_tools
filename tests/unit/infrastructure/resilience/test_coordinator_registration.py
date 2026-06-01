"""Smoke-тесты для ResilienceCoordinator + register_all_components ([wave:s17/k2-w5]).

Покрывают:
    1. Канонический список компонентов RESILIENCE_COMPONENTS.
    2. Singleton поведение get/set_resilience_coordinator.
    3. Graceful fallback register_all_components при wiring-failure отдельного компонента
       (не валит весь bootstrap).
    4. coordinator.status() возвращает корректные ComponentStatus после успешной регистрации.
    5. apply_policy декоратор сохраняет signature функции.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from src.backend.core.config.services.resilience import (
    BreakerProfile,
    FallbackPolicy,
    ResilienceSettings,
)
from src.backend.infrastructure.resilience.coordinator import (
    ComponentStatus,
    ResilienceCoordinator,
    get_resilience_coordinator,
    set_resilience_coordinator,
)
from src.backend.infrastructure.resilience.registration import (
    RESILIENCE_COMPONENTS,
    register_all_components,
)


def test_resilience_components_canonical_11() -> None:
    """RESILIENCE_COMPONENTS содержит ровно 11 канонических компонентов W26."""
    expected = {
        "db_main",
        "redis",
        "minio",
        "vault",
        "clickhouse",
        "mongodb",
        "elasticsearch",
        "kafka",
        "clamav",
        "smtp",
        "express",
    }
    assert set(RESILIENCE_COMPONENTS) == expected
    assert len(RESILIENCE_COMPONENTS) == 11


def test_get_resilience_coordinator_returns_singleton() -> None:
    """Повторные вызовы get_resilience_coordinator() возвращают тот же instance."""
    set_resilience_coordinator(None)  # сброс перед тестом
    coord1 = get_resilience_coordinator()
    coord2 = get_resilience_coordinator()
    assert coord1 is coord2
    set_resilience_coordinator(None)


def test_set_resilience_coordinator_resets_singleton() -> None:
    """set_resilience_coordinator(None) сбрасывает singleton."""
    set_resilience_coordinator(None)
    coord1 = get_resilience_coordinator()
    set_resilience_coordinator(None)
    coord2 = get_resilience_coordinator()
    assert coord1 is not coord2
    set_resilience_coordinator(None)


def test_register_all_components_graceful_on_wiring_failure() -> None:
    """Wiring-failure отдельного компонента не валит весь bootstrap (W26.4 контракт)."""
    coord = ResilienceCoordinator()
    settings = ResilienceSettings()

    # Принудительный failure: подменяем один из registrar'ов через patch.dict.
    # _REGISTRARS — module-level dict, держит references на функции, поэтому
    # patch на сам module-attribute не повлияет; нужно patch.dict.
    def _raising_registrar(*args, **kwargs) -> None:
        raise RuntimeError("simulated wiring failure")

    from src.backend.infrastructure.resilience import registration as reg_module

    with patch.dict(
        reg_module._REGISTRARS,
        {"clickhouse": _raising_registrar},
    ):
        # Не должно бросать — registration должен поглотить exception.
        register_all_components(coord, settings)

    # clickhouse registrar бросил RuntimeError → компонент НЕ зарегистрирован.
    assert "clickhouse" not in coord.list_components()


def test_register_all_components_succeeds_with_default_settings() -> None:
    """register_all_components завершается без exception на default ResilienceSettings."""
    coord = ResilienceCoordinator()
    settings = ResilienceSettings()
    # Сама по себе функция не должна бросать даже если все backends недоступны.
    register_all_components(coord, settings)
    # Coordinator может иметь от 0 до 11 компонентов в зависимости от deps.
    assert isinstance(coord.list_components(), list)


def test_coordinator_status_returns_component_status_dict() -> None:
    """coordinator.status() возвращает dict[str, ComponentStatus]."""
    coord = ResilienceCoordinator()
    settings = ResilienceSettings()
    register_all_components(coord, settings)
    status = coord.status()
    assert isinstance(status, dict)
    for name, comp_status in status.items():
        assert isinstance(name, str)
        assert isinstance(comp_status, ComponentStatus)
        assert comp_status.name == name
        assert comp_status.breaker_state in {"closed", "open", "half_open"}
        assert comp_status.mode in {"auto", "forced", "off"}


def test_apply_policy_decorator_preserves_signature() -> None:
    """apply_policy декоратор сохраняет __name__ и __qualname__ исходной функции."""
    coord = ResilienceCoordinator()

    @coord.apply_policy(component="test_component", name="my_callsite")
    async def fetch_data(arg: int) -> int:
        """Тестовая функция."""
        return arg * 2

    assert fetch_data.__name__ == "fetch_data"
    assert fetch_data.__doc__ == "Тестовая функция."

    # Smoke: реальный вызов работает без breaker/retry/rate_limiter.
    result = asyncio.run(fetch_data(21))
    assert result == 42


def test_register_from_settings_uses_fallback_policy() -> None:
    """register_from_settings берёт chain и mode из settings.fallbacks."""
    coord = ResilienceCoordinator()
    settings = ResilienceSettings(
        fallbacks={
            "test_svc": FallbackPolicy(chain=["bk1", "bk2"], mode="auto"),
        },
        breakers={
            "test_svc": BreakerProfile(threshold=3, ttl=15.0),
        },
    )

    async def primary() -> str:
        return "primary"

    async def bk1() -> str:
        return "bk1"

    async def bk2() -> str:
        return "bk2"

    coord.register_from_settings(
        component="test_svc",
        primary=primary,
        fallbacks={"bk1": bk1, "bk2": bk2},
        settings=settings,
    )
    status = coord.status()["test_svc"]
    assert status.chain == ["bk1", "bk2"]
    assert status.mode == "auto"


@pytest.mark.asyncio
async def test_register_from_settings_forced_mode_skips_primary() -> None:
    """mode='forced' пропускает primary даже если он есть (dev_light паттерн)."""
    coord = ResilienceCoordinator()
    settings = ResilienceSettings(
        fallbacks={"svc": FallbackPolicy(chain=["fb"], mode="forced")},
    )

    primary_called = False

    async def primary() -> str:
        nonlocal primary_called
        primary_called = True
        return "primary"

    async def fb() -> str:
        return "fallback"

    coord.register_from_settings(
        component="svc",
        primary=primary,
        fallbacks={"fb": fb},
        settings=settings,
    )
    result = await coord.call("svc")
    assert result == "fallback"
    assert primary_called is False
