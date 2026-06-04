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


def test_retry_alias() -> None:
    """``Retry`` — каноническое имя, alias на ``RetryPolicy``."""
    assert Retry is RetryPolicy


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
            max_attempts=3, initial_backoff=0.001, backoff_multiplier=1.0, jitter=0.0
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
            max_attempts=2, initial_backoff=0.001, backoff_multiplier=1.0, jitter=0.0
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


@pytest.mark.asyncio
async def test_retry_budget_exhausted_not_retried() -> None:
    """RetryBudgetExhausted не должен вызывать повторные попытки."""
    from src.backend.core.resilience.retry_budget import RetryBudget

    budget = RetryBudget(name="test-budget", ratio=0.0)
    policy = RetryPolicy(
        max_attempts=5,
        initial_backoff=0.001,
        backoff_multiplier=1.0,
        jitter=0.0,
        budget=budget,
    )

    counter = {"calls": 0}

    @with_retry(policy)
    async def flaky() -> str:
        counter["calls"] += 1
        raise RuntimeError("fail")

    # Бюджет исчерпан сразу → первая попытка пройдёт,
    # вторая попытка (retry) блокируется бюджетом до вызова fn.
    with pytest.raises(RetryBudgetExhausted):
        await flaky()
    # Функция вызвана ровно 1 раз: оригинальная попытка.
    # Retry-attempt отклонён бюджетом, fn не дёргалась повторно.
    assert counter["calls"] == 1
