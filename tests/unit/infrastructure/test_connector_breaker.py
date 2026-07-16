"""Tests for @with_breaker decorator."""

from __future__ import annotations

import pytest

from src.backend.core.resilience.connector_breaker import (
    CircuitOpen,
    with_breaker,
)
from src.backend.core.resilience.breaker import get_breaker_registry

# ruff: noqa: S101


@pytest.mark.unit
@pytest.mark.asyncio
async def test_decorator_passes_through_when_closed() -> None:
    """При closed-state декоратор пропускает вызов к функции."""

    @with_breaker("test_pass", failure_threshold=3)
    async def call_me() -> str:
        return "ok"

    result = await call_me()
    assert result == "ok"
    assert get_breaker_registry().get("test_pass") is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_decorator_opens_after_threshold() -> None:
    """После ``failure_threshold`` failures breaker переходит в open и
    короткозамыкает последующие вызовы через ``CircuitOpen``.
    """
    name = "test_open_threshold"

    @with_breaker(name, failure_threshold=2, recovery_seconds=60.0)
    async def always_fail() -> None:
        raise RuntimeError("oops")

    # Первые 2 failures — реальные исключения RuntimeError.
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await always_fail()

    # После threshold breaker должен быть open → CircuitOpen.
    with pytest.raises(CircuitOpen):
        await always_fail()
