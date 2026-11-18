"""Регресс-тесты: batch-операции RedisBackend идут под circuit breaker.

До фикса (wave 34, infra-аудит) ``mget_pipelined`` / ``mset_pipelined``
обходили ``ClientCircuitBreaker`` (в отличие от всех остальных операций
backend'а): при упавшем Redis они висели до socket-таймаута вместо
быстрого ``CircuitOpen`` — фасад не мог деградировать в memory/disk.

Покрывает:

* при открытом breaker batch-операция падает ``CircuitOpen`` (быстро);
* при закрытом breaker batch-операция доходит до клиента.

Breaker'ы изолированы по уникальному имени (общий реестр глобален) —
тест не влияет на остальные.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.backend.core.resilience.breaker import CircuitOpen
from src.backend.infrastructure.cache.backends.redis import RedisBackend
from src.backend.infrastructure.resilience.client_breaker import ClientCircuitBreaker


@pytest.fixture
def client() -> AsyncMock:
    """Замоканный ``redis.asyncio.Redis``-клиент."""
    mock = AsyncMock()
    mock.scan_iter = MagicMock()
    pipeline = MagicMock()
    pipeline.__aenter__ = AsyncMock(return_value=pipeline)
    pipeline.__aexit__ = AsyncMock(return_value=None)
    pipeline.execute = AsyncMock(return_value=[b"v"])
    mock.pipeline = MagicMock(return_value=pipeline)
    return mock


@pytest.fixture
def backend(client: AsyncMock) -> RedisBackend:
    """RedisBackend с изолированным breaker'ом."""
    breaker = ClientCircuitBreaker(
        name=f"test.cache.redis.{uuid4().hex}",
        failure_threshold=2,
        recovery_timeout=30.0,
        host="test",
    )
    return RedisBackend(client=client, breaker=breaker)


async def _open_breaker(backend: RedisBackend, client: AsyncMock) -> None:
    """Добиться открытия breaker'а неуспешными вызовами."""
    client.get.side_effect = ConnectionError("redis down")
    for _ in range(3):
        try:
            await backend.get("warmup")
        except ConnectionError, CircuitOpen:
            # После открытия breaker'а следующий вызов падает CircuitOpen.
            pass
    assert backend.breaker.is_open()


@pytest.mark.asyncio
async def test_mget_pipelined_uses_breaker(
    backend: RedisBackend, client: AsyncMock
) -> None:
    """Открытый breaker → ``CircuitOpen`` вместо обращения к Redis."""
    await _open_breaker(backend, client)

    with pytest.raises(CircuitOpen):
        await backend.mget_pipelined(["k1", "k2"])


@pytest.mark.asyncio
async def test_mset_pipelined_uses_breaker(
    backend: RedisBackend, client: AsyncMock
) -> None:
    """Открытый breaker → ``CircuitOpen`` вместо записи в Redis."""
    await _open_breaker(backend, client)

    with pytest.raises(CircuitOpen):
        await backend.mset_pipelined({"k1": b"v"})


@pytest.mark.asyncio
async def test_mget_pipelined_success(backend: RedisBackend, client: AsyncMock) -> None:
    """При закрытом breaker batch-операция доходит до клиента."""
    result = await backend.mget_pipelined(["k1"])
    assert result == [b"v"]
    client.pipeline.assert_called_once()
