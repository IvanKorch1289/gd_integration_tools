"""Тесты unified circuit breaker (Sprint 1 V16 Single-Entry, Step 3.2)."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.resilience.breaker import (
    Breaker,
    BreakerRegistry,
    BreakerSpec,
    CircuitBreaker,
    CircuitOpen,
    get_breaker_registry,
)


def test_circuit_breaker_alias() -> None:
    """``CircuitBreaker`` — каноническое имя, alias на ``Breaker``."""
    assert CircuitBreaker is Breaker


def test_breaker_registry_singleton() -> None:
    """``get_breaker_registry`` lru_cache даёт стабильный singleton."""
    a = get_breaker_registry()
    b = get_breaker_registry()
    assert a is b
    assert isinstance(a, BreakerRegistry)


def test_breaker_registry_get_or_create_idempotent() -> None:
    """Повторный ``get_or_create(name)`` возвращает тот же breaker."""
    registry = BreakerRegistry()
    b1 = registry.get_or_create("test_component", BreakerSpec())
    b2 = registry.get_or_create("test_component", BreakerSpec())
    assert b1 is b2
    assert b1.state == "closed"


def test_breaker_initial_state_closed() -> None:
    """Только что созданный breaker всегда ``closed``."""
    registry = BreakerRegistry()
    breaker = registry.get_or_create("fresh", BreakerSpec())
    assert breaker.state == "closed"
    assert breaker.is_open is False


@pytest.mark.asyncio
async def test_breaker_guard_allows_when_closed() -> None:
    """``Breaker.guard()`` пропускает вызов при closed-state."""
    registry = BreakerRegistry()
    breaker = registry.get_or_create("ok-flow", BreakerSpec())
    async with breaker.guard():
        result = 42
    assert result == 42
    assert breaker.state == "closed"


def test_circuit_open_is_purgatory_alias() -> None:
    """``CircuitOpen`` — re-export ``purgatory.OpenedState``."""
    from purgatory.domain.model import OpenedState

    assert CircuitOpen is OpenedState
