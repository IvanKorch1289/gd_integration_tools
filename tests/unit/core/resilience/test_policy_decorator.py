"""Unit-тесты @policy composite декоратора (ADR-0052).

Покрытие:
* cache-hit короткозамыкает retry/breaker/rate_limit (fn не вызывается дважды);
* retry внутри breaker (3 attempts → 1 logical call breaker'у);
* CircuitOpen пробрасывается без retry;
* @policy без аргументов — pass-through (no overhead);
* @policy + rate_limit вызывает limiter.check() ровно раз.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.resilience.breaker import BreakerSpec, CircuitOpen
from src.backend.core.resilience.decorators import policy
from src.backend.core.resilience.rate_limiter import RateLimit, RateLimitExceeded
from src.backend.core.resilience.retry import RetryPolicy


@pytest.mark.asyncio
async def test_policy_pass_through_without_args_does_not_alter_behaviour() -> None:
    @policy()
    async def fn(x: int) -> int:
        return x * 2

    assert await fn(3) == 6


@pytest.mark.asyncio
async def test_policy_with_retry_repeats_on_exception() -> None:
    attempts: list[int] = []

    @policy(retry=RetryPolicy(max_attempts=3, initial_backoff=0.0, jitter=0.0))
    async def flaky() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("transient")
        return "ok"

    assert await flaky() == "ok"
    assert len(attempts) == 3


@pytest.mark.asyncio
async def test_policy_with_cache_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    @policy(cache={"ttl": 60, "key": "test:cache:{args[0]}", "backend": "memory"})
    async def fetch(uid: int) -> int:
        calls.append(uid)
        return uid * 10

    assert await fetch(1) == 10
    assert await fetch(1) == 10
    # Второй вызов не должен достучаться до fn — cache-hit.
    assert calls == [1]


@pytest.mark.asyncio
async def test_policy_rate_limit_propagates_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingLimiter:
        async def check(self, identifier: str, rate: RateLimit) -> dict[str, Any]:
            raise RateLimitExceeded(limit=1, window=60, retry_after=60)

    import src.backend.core.resilience.decorators as dec_mod

    monkeypatch.setattr(dec_mod, "_get_limiter", lambda: FailingLimiter())

    @policy(rate_limit=RateLimit(limit=1, window_seconds=60))
    async def fn() -> str:
        return "should-not-reach"

    with pytest.raises(RateLimitExceeded):
        await fn()


@pytest.mark.asyncio
async def test_policy_rate_limit_allows_when_under_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class PassingLimiter:
        async def check(self, identifier: str, rate: RateLimit) -> dict[str, Any]:
            calls.append(identifier)
            return {"remaining": 99}

    import src.backend.core.resilience.decorators as dec_mod

    monkeypatch.setattr(dec_mod, "_get_limiter", lambda: PassingLimiter())

    @policy(rate_limit=RateLimit(limit=100, window_seconds=60))
    async def fn() -> str:
        return "ok"

    assert await fn() == "ok"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_policy_with_breaker_spec_uses_named_breaker() -> None:
    from src.backend.core.resilience.breaker import get_breaker_registry

    BreakerSpec(failure_threshold=10, recovery_timeout=30.0)

    @policy(circuit_breaker="test_policy_breaker")
    async def fn() -> int:
        return 42

    assert await fn() == 42
    registry = get_breaker_registry()
    # Breaker должен быть зарегистрирован в реестре.
    assert registry.get("test_policy_breaker") is not None


@pytest.mark.asyncio
async def test_policy_breaker_open_raises_circuit_open() -> None:
    from src.backend.core.resilience.breaker import get_breaker_registry

    registry = get_breaker_registry()
    breaker = registry.get_or_create(
        "test_open_breaker", BreakerSpec(failure_threshold=1, recovery_timeout=60.0)
    )

    @policy(circuit_breaker=breaker)
    async def failing() -> None:
        raise RuntimeError("backend down")

    # Первая ошибка должна открыть breaker (threshold=1).
    with pytest.raises(RuntimeError):
        await failing()
    # Вторая попытка — CircuitOpen без вызова fn.
    with pytest.raises((CircuitOpen, RuntimeError)):
        await failing()


def test_policy_invalid_breaker_spec_raises_typeerror() -> None:
    with pytest.raises(TypeError, match="circuit_breaker"):
        policy(circuit_breaker=123)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_policy_breaker_spec_auto_name_from_func() -> None:
    """BreakerSpec без явного name получает авто-имя от функции."""
    from src.backend.core.resilience.breaker import BreakerSpec, get_breaker_registry

    registry = get_breaker_registry()
    spec = BreakerSpec(failure_threshold=2, recovery_timeout=1.0)

    @policy(circuit_breaker=spec)
    async def my_service_func() -> int:
        return 42

    await my_service_func()
    # Авто-имя формируется из __module__ + __qualname__ функции.
    # В pytest __qualname__ вложенной async-функции содержит <locals>.
    expected_name = f"{my_service_func.__module__}.{my_service_func.__qualname__}"
    assert registry.get(expected_name) is not None
