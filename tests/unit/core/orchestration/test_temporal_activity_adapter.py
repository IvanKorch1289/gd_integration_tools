"""Тесты K2 W1 TemporalActivityWrapper / wrap_as_temporal_activity."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.orchestration.temporal_activity_adapter import (
    TemporalActivityWrapper,
    wrap_as_temporal_activity,
)


@pytest.mark.asyncio
async def test_wrap_async_callable_executes() -> None:
    """Async-callable оборачивается и возвращает корректный результат."""

    async def add(a: int, b: int) -> int:
        return a + b

    activity = wrap_as_temporal_activity(add)
    assert isinstance(activity, TemporalActivityWrapper)
    assert activity.name.endswith("add")

    result = await activity(2, 3)
    assert result == 5


@pytest.mark.asyncio
async def test_wrap_sync_callable_executes_in_executor() -> None:
    """Sync-callable выполняется через run_in_executor."""

    def multiply(a: int, b: int) -> int:
        return a * b

    activity = wrap_as_temporal_activity(multiply, name="multiply.activity")
    assert activity.name == "multiply.activity"

    result = await activity(4, 5)
    assert result == 20


@pytest.mark.asyncio
async def test_wrap_idempotency_same_callable_returns_same_wrapper() -> None:
    """Повторный wrap того же callable возвращает один и тот же объект."""

    async def normalize(data: dict) -> dict:
        return {"normalized": True, **data}

    a1 = wrap_as_temporal_activity(normalize)
    a2 = wrap_as_temporal_activity(normalize)
    a3 = wrap_as_temporal_activity(a1)  # уже обёрнутая → idempotent

    assert a1 is a2
    assert a3 is a1


@pytest.mark.asyncio
async def test_error_propagation() -> None:
    """Исключение из обёрнутой функции пробрасывается наружу."""

    class MyError(Exception):
        pass

    async def failing() -> None:
        raise MyError("boom")

    activity = wrap_as_temporal_activity(failing)
    with pytest.raises(MyError, match="boom"):
        await activity()
