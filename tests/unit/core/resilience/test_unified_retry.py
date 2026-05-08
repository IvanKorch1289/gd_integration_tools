"""Тесты unified retry (Sprint 1 V16 Single-Entry, Step 3.2)."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.resilience.retry import (
    Retry,
    RetryBudgetExhausted,
    RetryPolicy,
    with_retry,
)
from src.backend.core.resilience.retry_budget import RetryBudget


def test_retry_alias() -> None:
    """``Retry`` — каноническое имя, alias на ``RetryPolicy``."""
    assert Retry is RetryPolicy


def test_infrastructure_shim_re_exports() -> None:
    """Backward-compat: импорты из ``infrastructure.resilience.retry`` работают."""
    from src.backend.infrastructure.resilience.retry import RetryPolicy as InfraPolicy
    from src.backend.infrastructure.resilience.retry import (
        with_retry as infra_with_retry,
    )

    assert InfraPolicy is RetryPolicy
    assert infra_with_retry is with_retry


def test_infrastructure_retry_budget_shim() -> None:
    """Backward-compat: ``RetryBudget`` доступен из infrastructure-shim."""
    from src.backend.infrastructure.resilience.retry_budget import (
        RetryBudget as InfraBudget,
    )
    from src.backend.infrastructure.resilience.retry_budget import (
        RetryBudgetExhausted as InfraExhausted,
    )

    assert InfraBudget is RetryBudget
    assert InfraExhausted is RetryBudgetExhausted


@pytest.mark.asyncio
async def test_with_retry_succeeds_on_first_attempt() -> None:
    """Успешная функция вызывается ровно один раз."""
    counter = {"calls": 0}

    @with_retry(RetryPolicy(max_attempts=3))
    async def ok_func() -> str:
        counter["calls"] += 1
        return "ok"

    assert await ok_func() == "ok"
    assert counter["calls"] == 1


@pytest.mark.asyncio
async def test_with_retry_retries_on_failure() -> None:
    """При падении функция вызывается до ``max_attempts`` раз."""
    counter = {"calls": 0}

    @with_retry(
        RetryPolicy(
            max_attempts=3,
            initial_backoff=0.001,
            backoff_multiplier=1.0,
            jitter=0.0,
        )
    )
    async def flaky_func() -> str:
        counter["calls"] += 1
        if counter["calls"] < 3:
            raise RuntimeError("flaky")
        return "ok"

    assert await flaky_func() == "ok"
    assert counter["calls"] == 3


@pytest.mark.asyncio
async def test_with_retry_reraises_on_exhaustion() -> None:
    """Исчерпание ``max_attempts`` пробрасывает последнее исключение."""
    counter = {"calls": 0}

    @with_retry(
        RetryPolicy(
            max_attempts=2,
            initial_backoff=0.001,
            backoff_multiplier=1.0,
            jitter=0.0,
        )
    )
    async def always_fails() -> str:
        counter["calls"] += 1
        raise RuntimeError("never works")

    with pytest.raises(RuntimeError, match="never works"):
        await always_fails()
    assert counter["calls"] == 2


def test_retry_budget_exhausted_has_name() -> None:
    """``RetryBudgetExhausted`` несёт имя budget'а в атрибуте ``name``."""
    exc = RetryBudgetExhausted("test-budget")
    assert exc.name == "test-budget"
    assert "test-budget" in str(exc)
