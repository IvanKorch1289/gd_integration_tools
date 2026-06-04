"""Unit-тесты для :class:`RedisBackend` (тонкая обёртка над redis.asyncio).

Используем :class:`unittest.mock.AsyncMock` вместо реального Redis —
``fakeredis`` не входит в dev-deps. Цель — проверить корректность
делегирования вызовов и формирование аргументов (``ex=ttl``,
``scan_iter`` для ``delete_pattern``).
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, call

import pytest

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
    """Замоканный ``redis.asyncio.Redis``-клиент."""
    mock = AsyncMock()
    # ``scan_iter`` обычно возвращает async-итератор синхронно.
    mock.scan_iter = MagicMock()
    return mock


@pytest.fixture
def backend(client: AsyncMock) -> RedisBackend:
    """RedisBackend с замоканным клиентом."""
    return RedisBackend(client=client)


async def test_get_delegates_to_client(
    backend: RedisBackend, client: AsyncMock
) -> None:
    """``get`` вызывает ``client.get(key)`` и возвращает результат."""
    client.get.return_value = b"value"
    result = await backend.get("key")
    assert result == b"value"
    client.get.assert_awaited_once_with("key")


async def test_get_missing_returns_none(
    backend: RedisBackend, client: AsyncMock
) -> None:
    """Если client.get возвращает None, backend возвращает None."""
    client.get.return_value = None
    assert await backend.get("missing") is None


async def test_set_without_ttl(backend: RedisBackend, client: AsyncMock) -> None:
    """``set`` без ttl вызывает ``client.set(key, value)`` без ``ex``."""
    await backend.set("k", b"v")
    client.set.assert_awaited_once_with("k", b"v")


async def test_set_with_ttl(backend: RedisBackend, client: AsyncMock) -> None:
    """``set`` с ttl вызывает ``client.set(key, value, ex=ttl)``."""
    await backend.set("k", b"v", ttl=60)
    client.set.assert_awaited_once_with("k", b"v", ex=60)


async def test_set_with_zero_ttl_treated_as_value(
    backend: RedisBackend, client: AsyncMock
) -> None:
    """ttl=0 не None — должно прокинуться как ex=0 (контракт backend'а)."""
    await backend.set("k", b"v", ttl=0)
    client.set.assert_awaited_once_with("k", b"v", ex=0)


async def test_delete_single_key(backend: RedisBackend, client: AsyncMock) -> None:
    """``delete`` для одного ключа делегирует в ``client.delete``."""
    await backend.delete("a")
    client.delete.assert_awaited_once_with("a")


async def test_delete_multiple_keys(backend: RedisBackend, client: AsyncMock) -> None:
    """``delete`` для нескольких ключей передаёт все аргументы за один вызов."""
    await backend.delete("a", "b", "c")
    client.delete.assert_awaited_once_with("a", "b", "c")


async def test_delete_no_keys_skips_call(
    backend: RedisBackend, client: AsyncMock
) -> None:
    """``delete`` без ключей — не вызывает client (избегаем DEL ()))."""
    await backend.delete()
    client.delete.assert_not_called()


async def test_delete_pattern_uses_scan_iter(
    backend: RedisBackend, client: AsyncMock
) -> None:
    """``delete_pattern`` итерирует через ``scan_iter`` и удаляет каждый ключ."""
    client.scan_iter.return_value = _AsyncIterator([b"a", b"b", b"c"])
    await backend.delete_pattern("user:*")
    client.scan_iter.assert_called_once_with(match="user:*", count=200)
    assert client.delete.await_count == 3
    client.delete.assert_has_awaits([call(b"a"), call(b"b"), call(b"c")])


async def test_delete_pattern_empty_iterator(
    backend: RedisBackend, client: AsyncMock
) -> None:
    """Пустой scan_iter не вызывает client.delete."""
    client.scan_iter.return_value = _AsyncIterator([])
    await backend.delete_pattern("none:*")
    client.delete.assert_not_called()


async def test_exists_true(backend: RedisBackend, client: AsyncMock) -> None:
    """``exists`` возвращает True если client.exists != 0."""
    client.exists.return_value = 1
    assert await backend.exists("k") is True
    client.exists.assert_awaited_once_with("k")


async def test_exists_false(backend: RedisBackend, client: AsyncMock) -> None:
    """``exists`` возвращает False если client.exists == 0."""
    client.exists.return_value = 0
    assert await backend.exists("k") is False


# ── Tag-index tests ────────────────────────────────────────────────────────────


async def test_bind_key_to_tag_adds_to_set(
    backend: RedisBackend, client: AsyncMock
) -> None:
    """``bind_key_to_tag`` вызывает SADD __cache_tag:{tag} {key}."""
    await backend.bind_key_to_tag("entity:orders", "orders:42")
    client.sadd.assert_awaited_once_with("__cache_tag:entity:orders", "orders:42")


async def test_delete_by_tag_removes_all_tagged_keys(
    backend: RedisBackend, client: AsyncMock
) -> None:
    """``delete_by_tag`` удаляет все ключи из SET и сам SET-индекс."""
    # SMEMBERS возвращает bytes-ключи → декодируются в str перед DEL
    client.smembers.return_value = {b"orders:1", b"orders:2"}
    removed = await backend.delete_by_tag("entity:orders")

    assert removed == 2
    client.smembers.assert_awaited_once_with("__cache_tag:entity:orders")
    # delete(*keys) — один вызов с двумя str-аргументами, затем DEL tag-index
    assert client.delete.await_count == 2
    # Проверяем структуру: первая DEL — ключи (str, порядок не определён),
    # вторая DEL — tag-index
    calls = client.delete.call_args_list
    # Tag-index DEL — всегда str, без __cache_tag: префикса в начале
    tag_del = [c for c in calls if c.args and c.args[0] == "__cache_tag:entity:orders"]
    key_del = [c for c in calls if c.args and c.args[0] != "__cache_tag:entity:orders"]
    assert len(tag_del) == 1
    assert len(key_del) == 1
    # Ключи — str, два аргумента
    assert len(key_del[0].args) == 2
    assert all(isinstance(k, str) for k in key_del[0].args)


async def test_delete_by_tag_empty_returns_zero(
    backend: RedisBackend, client: AsyncMock
) -> None:
    """Пустой tag-index → возвращает 0, DEL не вызывается."""
    client.smembers.return_value = set()
    removed = await backend.delete_by_tag("nonexistent:tag")

    assert removed == 0
    client.delete.assert_not_called()


async def test_delete_by_tag_decodes_bytes_keys(
    backend: RedisBackend, client: AsyncMock
) -> None:
    """Ключи из SMEMBERS декодируются из bytes в str перед DEL."""
    client.smembers.return_value = {b"cache:key:1", b"cache:key:2"}
    await backend.delete_by_tag("table:orders")

    # Проверяем что DEL вызван с str-ключами (bytes декодированы)
    calls = client.delete.call_args_list
    assert len(calls) == 2
    # Первый вызов: delete(key1, key2) — ключи декодированы в str
    key_call_args = calls[0].args
    assert all(isinstance(k, str) for k in key_call_args)
    assert set(key_call_args) == {"cache:key:1", "cache:key:2"}
    # Второй вызов: DEL tag-index
    assert calls[1].args == ("__cache_tag:table:orders",)


async def test_delete_by_pattern_returns_count(
    backend: RedisBackend, client: AsyncMock
) -> None:
    """``delete_by_pattern`` (новый, возвращающий int) считает удалённые ключи."""
    client.scan_iter.return_value = _AsyncIterator([b"a", b"b"])
    removed = await backend.delete_by_pattern("cache:orders:*")

    assert removed == 2
    assert client.delete.await_count == 2
