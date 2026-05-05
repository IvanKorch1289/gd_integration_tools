"""Unit-тесты для :class:`KeyDBBackend` (drop-in для Redis).

KeyDB наследуется от RedisBackend (RESP-совместим), поэтому реиспользуем
подход с :class:`unittest.mock.AsyncMock`. Дополнительно проверяем
``active_replica``-флаг конструктора.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.cache.backends.keydb import KeyDBBackend
from src.backend.infrastructure.cache.backends.redis import RedisBackend


class _AsyncIterator:
    """Async-итератор-обёртка для ``scan_iter``-результата."""

    def __init__(self, items: list[Any]) -> None:
        self._iter = iter(items)

    def __aiter__(self) -> "_AsyncIterator":
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


@pytest.fixture
def client() -> AsyncMock:
    """Замоканный RESP-совместимый клиент."""
    mock = AsyncMock()
    mock.scan_iter = MagicMock()
    return mock


@pytest.fixture
def backend(client: AsyncMock) -> KeyDBBackend:
    """KeyDBBackend с замоканным клиентом."""
    return KeyDBBackend(client=client)


def test_inherits_redis_backend(backend: KeyDBBackend) -> None:
    """KeyDBBackend — наследник RedisBackend (drop-in замена)."""
    assert isinstance(backend, RedisBackend)


def test_active_replica_default_false(client: AsyncMock) -> None:
    """``active_replica`` по умолчанию False."""
    b = KeyDBBackend(client=client)
    assert b._active_replica is False


def test_active_replica_can_be_enabled(client: AsyncMock) -> None:
    """``active_replica=True`` корректно сохраняется."""
    b = KeyDBBackend(client=client, active_replica=True)
    assert b._active_replica is True


async def test_get_delegates_to_client(
    backend: KeyDBBackend, client: AsyncMock
) -> None:
    """``get`` делегирует в client (унаследовано из RedisBackend)."""
    client.get.return_value = b"value"
    assert await backend.get("k") == b"value"
    client.get.assert_awaited_once_with("k")


async def test_set_with_ttl(
    backend: KeyDBBackend, client: AsyncMock
) -> None:
    """``set`` с ttl передаёт ``ex=ttl`` в client (унаследовано)."""
    await backend.set("k", b"v", ttl=120)
    client.set.assert_awaited_once_with("k", b"v", ex=120)


async def test_set_without_ttl(
    backend: KeyDBBackend, client: AsyncMock
) -> None:
    """``set`` без ttl не передаёт ``ex``."""
    await backend.set("k", b"v")
    client.set.assert_awaited_once_with("k", b"v")


async def test_delete_multiple(
    backend: KeyDBBackend, client: AsyncMock
) -> None:
    """``delete`` нескольких ключей — один вызов client.delete."""
    await backend.delete("a", "b")
    client.delete.assert_awaited_once_with("a", "b")


async def test_delete_no_keys(
    backend: KeyDBBackend, client: AsyncMock
) -> None:
    """``delete`` без ключей — без вызова client."""
    await backend.delete()
    client.delete.assert_not_called()


async def test_delete_pattern_via_scan_iter(
    backend: KeyDBBackend, client: AsyncMock
) -> None:
    """``delete_pattern`` использует scan_iter (наследовано)."""
    client.scan_iter.return_value = _AsyncIterator([b"x", b"y"])
    await backend.delete_pattern("p:*")
    client.scan_iter.assert_called_once_with(match="p:*", count=200)
    assert client.delete.await_count == 2


async def test_exists_true(
    backend: KeyDBBackend, client: AsyncMock
) -> None:
    """``exists`` возвращает True для непустого результата."""
    client.exists.return_value = 1
    assert await backend.exists("k") is True


async def test_exists_false(
    backend: KeyDBBackend, client: AsyncMock
) -> None:
    """``exists`` возвращает False для нулевого результата."""
    client.exists.return_value = 0
    assert await backend.exists("k") is False
