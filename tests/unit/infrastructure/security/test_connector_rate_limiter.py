"""Tests for ConnectorRateLimiter (Security Wave S1)."""

from __future__ import annotations

import pytest

from src.backend.infrastructure.security.connector_rate_limiter import (
    ConnectorRateLimiter,
    get_connector_rate_limiter,
)
from src.backend.infrastructure.resilience.unified_rate_limiter import (
    RateLimitExceeded,
)


@pytest.mark.unit
async def test_default_policy_when_not_registered() -> None:
    """Незарегистрированный коннектор использует DEFAULT_POLICY (100/s)."""
    limiter = ConnectorRateLimiter()
    # Должно пройти (Redis fail-open в тестах, fallback возвращает remaining=limit).
    await limiter.check("unknown_connector")


@pytest.mark.unit
async def test_register_custom_rate() -> None:
    """После register — кастомный rate используется."""
    limiter = ConnectorRateLimiter()
    limiter.register("kafka_main", "10/s", 5)
    # Первые вызовы не должны падать (Redis fail-open в test env).
    for _ in range(4):
        await limiter.check("kafka_main")


@pytest.mark.unit
async def test_with_limit_wrapper() -> None:
    """with_limit() оборачивает async-функцию после rate-check."""
    limiter = ConnectorRateLimiter()
    limiter.register("http_sink_1", "1000/s", 100)

    async def fake_call() -> str:
        return "ok"

    result = await limiter.with_limit("http_sink_1", fake_call)
    assert result == "ok"


@pytest.mark.unit
async def test_with_limit_passes_args() -> None:
    """with_limit() пробрасывает args/kwargs в обёрнутую функцию."""
    limiter = ConnectorRateLimiter()
    limiter.register("grpc_main", "1000/s", 100)

    async def add(a: int, b: int, *, mul: int = 1) -> int:
        return (a + b) * mul

    result = await limiter.with_limit("grpc_main", add, 2, 3, mul=4)
    assert result == 20


@pytest.mark.unit
async def test_register_is_idempotent() -> None:
    """Повторный register с тем же именем перезаписывает политику."""
    limiter = ConnectorRateLimiter()
    limiter.register("nats", "100/s", 100)
    limiter.register("nats", "500/s", 500)
    rate_str, burst, _window = limiter._resolve("nats")
    assert rate_str == "500/s"
    assert burst == 500


@pytest.mark.unit
async def test_singleton_returns_same_instance() -> None:
    """get_connector_rate_limiter — singleton."""
    a = get_connector_rate_limiter()
    b = get_connector_rate_limiter()
    assert a is b


@pytest.mark.unit
async def test_check_with_scope_uses_isolated_key() -> None:
    """scope добавляется в Redis-ключ (изоляция между scope'ами)."""
    limiter = ConnectorRateLimiter()
    limiter.register("kafka", "1000/s", 1000)
    # Разные scope'ы не должны конфликтовать.
    await limiter.check("kafka", scope="topic_a")
    await limiter.check("kafka", scope="topic_b")
