"""Wave 18 (ADR-0391): circuit breaker на пути cache-фасада.

Дефект 6 (medium): ``RedisBackend`` работает напрямую с raw
``redis.asyncio.Redis`` и идёт мимо ``RedisClient.execute()`` — там CB
есть, а тут нет. При упавшем Redis каждая операция жгла полный
socket-таймаут (в base.yml было 600 с) → запрос висел на 10 минут.

Ожидание: после N подряд отказов breaker открывается и следующие вызовы
падают быстро (``CircuitOpen``) — фасад деградирует в memory/disk без
ожидания сокета.
"""

from __future__ import annotations

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from src.backend.infrastructure.cache.backends.redis import RedisBackend
from src.backend.infrastructure.resilience.client_breaker import (
    CircuitOpen,
    ClientCircuitBreaker,
)


class _FailingClient:
    """Raw redis-клиент, который всегда падает."""

    def __init__(self) -> None:
        self.calls = 0

    async def get(self, key: str) -> bytes | None:  # noqa: ARG002
        """GET — всегда ошибка соединения."""
        self.calls += 1
        raise RedisConnectionError("connection refused")

    async def set(self, key: str, value: bytes, ex: int | None = None) -> bool:  # noqa: ARG002
        """SET — всегда ошибка соединения."""
        self.calls += 1
        raise RedisConnectionError("connection refused")


def _breaker(name: str) -> ClientCircuitBreaker:
    """Изолированный breaker (уникальное имя — без влияния на глобальный)."""
    return ClientCircuitBreaker(
        name=name,
        failure_threshold=3,
        recovery_timeout=60.0,
        host="test",
    )


@pytest.mark.unit
def test_redis_backend_has_circuit_breaker() -> None:
    """RedisBackend имеет circuit breaker (raw-путь не остаётся без CB)."""
    backend = RedisBackend(client=_FailingClient())
    assert backend.breaker is not None


@pytest.mark.asyncio
async def test_redis_backend_opens_circuit_after_repeated_failures() -> None:
    """После N отказов breaker открывается → быстрый CircuitOpen."""
    client = _FailingClient()
    backend = RedisBackend(client=client, breaker=_breaker("test.cache.redis.open"))

    for _ in range(3):
        with pytest.raises(RedisConnectionError):
            await backend.get("k")

    calls_before = client.calls
    with pytest.raises(CircuitOpen):
        await backend.get("k")

    # Fast-fail: клиент больше не дёргается.
    assert client.calls == calls_before


@pytest.mark.asyncio
async def test_redis_backend_set_is_guarded_by_breaker() -> None:
    """SET тоже защищён breaker'ом (write-путь)."""
    backend = RedisBackend(
        client=_FailingClient(), breaker=_breaker("test.cache.redis.set")
    )

    with pytest.raises(RedisConnectionError):
        await backend.set("k", b"v")


@pytest.mark.asyncio
async def test_redis_backend_successful_call_keeps_circuit_closed() -> None:
    """Успешная операция не открывает breaker."""

    class _OkClient:
        async def get(self, key: str) -> bytes | None:
            """GET — успех."""
            return b"v"

    backend = RedisBackend(
        client=_OkClient(), breaker=_breaker("test.cache.redis.ok")
    )

    assert await backend.get("k") == b"v"
    assert backend.breaker.is_open() is False


@pytest.mark.unit
def test_breaker_is_shared_by_default_name() -> None:
    """Дефолтный breaker имеет стабильное имя (для метрик и fast-fail)."""
    backend = RedisBackend(client=_FailingClient())
    assert backend.breaker.name == "cache.redis"
