"""Tests for @with_retry decorator (Security Wave S4)."""
from __future__ import annotations

import pytest

from src.backend.core.resilience.connector_retry import with_retry


@pytest.mark.unit
async def test_retry_succeeds_on_first_try() -> None:
    @with_retry(max_attempts=3)
    async def call_me() -> str:
        return "ok"

    result = await call_me()
    assert result == "ok"


@pytest.mark.unit
async def test_retry_succeeds_after_transient_failures() -> None:
    counter = {"n": 0}

    @with_retry(max_attempts=3, initial_backoff=0.01)
    async def flaky() -> str:
        counter["n"] += 1
        if counter["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    result = await flaky()
    assert result == "ok"
    assert counter["n"] == 3


@pytest.mark.unit
async def test_retry_gives_up_after_max_attempts() -> None:
    counter = {"n": 0}

    @with_retry(max_attempts=2, initial_backoff=0.01)
    async def always_fail() -> None:
        counter["n"] += 1
        raise ConnectionError("perma")

    with pytest.raises(ConnectionError):
        await always_fail()
    assert counter["n"] == 2


@pytest.mark.unit
async def test_retry_does_not_retry_on_unmatched_exception() -> None:
    counter = {"n": 0}

    @with_retry(max_attempts=3, initial_backoff=0.01)
    async def value_error() -> None:
        counter["n"] += 1
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await value_error()
    # Нет retry для non-default exceptions — ValueError не входит в
    # (ConnectionError, TimeoutError, OSError).
    assert counter["n"] == 1


@pytest.mark.unit
async def test_retry_retries_on_os_error() -> None:
    counter = {"n": 0}

    @with_retry(max_attempts=3, initial_backoff=0.01)
    async def os_error_then_ok() -> str:
        counter["n"] += 1
        if counter["n"] < 2:
            raise OSError("disk full")
        return "ok"

    result = await os_error_then_ok()
    assert result == "ok"
    assert counter["n"] == 2


@pytest.mark.unit
async def test_retry_custom_retry_on() -> None:
    counter = {"n": 0}

    class MyTransientError(RuntimeError):
        pass

    @with_retry(
        max_attempts=3,
        initial_backoff=0.01,
        retry_on=(MyTransientError,),
    )
    async def fn() -> str:
        counter["n"] += 1
        if counter["n"] < 2:
            raise MyTransientError("transient")
        return "ok"

    result = await fn()
    assert result == "ok"
    assert counter["n"] == 2


@pytest.mark.unit
async def test_retry_jitter_does_not_break_success() -> None:
    """Smoke-test: jitter=True не ломает успешный вызов."""
    @with_retry(max_attempts=5, jitter=True)
    async def call_me() -> str:
        return "ok"

    assert await call_me() == "ok"


@pytest.mark.unit
async def test_retry_preserves_function_metadata() -> None:
    @with_retry(max_attempts=3)
    async def my_named_fn() -> str:
        """My docstring."""
        return "ok"

    assert my_named_fn.__name__ == "my_named_fn"
    assert "My docstring" in (my_named_fn.__doc__ or "")
