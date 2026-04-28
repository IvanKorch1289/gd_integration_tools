"""Unit-тесты для :class:`MemcachedBackend`.

``aiomcache`` — опциональная зависимость; если не установлена, тесты
скипаем через ``pytest.importorskip``. Сам клиент мокаем через
:class:`unittest.mock.AsyncMock`, чтобы не поднимать реальный memcached.
"""

# ruff: noqa: S101

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

# aiomcache опционален — без него MemcachedBackend.__init__ бросает RuntimeError.
pytest.importorskip("aiomcache")

from src.infrastructure.cache.backends.memcached import MemcachedBackend  # noqa: E402


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> MemcachedBackend:
    """MemcachedBackend с замоканным внутренним ``aiomcache.Client``."""
    b = MemcachedBackend(host="127.0.0.1", port=11211, default_ttl=300)
    fake_client = AsyncMock()
    monkeypatch.setattr(b, "_client", fake_client)
    return b


async def test_get_returns_value(backend: MemcachedBackend) -> None:
    """``get`` делегирует в client с bytes-ключом и возвращает значение."""
    backend._client.get.return_value = b"value"
    result = await backend.get("key1")
    assert result == b"value"
    backend._client.get.assert_awaited_once_with(b"key1")


async def test_get_missing_returns_none(backend: MemcachedBackend) -> None:
    """``get`` возвращает None если client.get вернул None."""
    backend._client.get.return_value = None
    assert await backend.get("missing") is None


async def test_set_with_ttl(backend: MemcachedBackend) -> None:
    """``set`` с ttl передаёт ``exptime=ttl`` в client.set."""
    await backend.set("k", b"v", ttl=60)
    backend._client.set.assert_awaited_once_with(b"k", b"v", exptime=60)


async def test_set_without_ttl_uses_default(
    backend: MemcachedBackend,
) -> None:
    """``set`` без ttl использует ``default_ttl`` из конструктора."""
    await backend.set("k", b"v")
    backend._client.set.assert_awaited_once_with(b"k", b"v", exptime=300)


async def test_delete_single_key(backend: MemcachedBackend) -> None:
    """``delete`` для одного ключа делегирует в client.delete."""
    await backend.delete("a")
    backend._client.delete.assert_awaited_once_with(b"a")


async def test_delete_multiple_keys(backend: MemcachedBackend) -> None:
    """``delete`` нескольких ключей вызывает client.delete отдельно для каждого.

    Memcached не поддерживает массовое удаление за один вызов.
    """
    await backend.delete("a", "b", "c")
    assert backend._client.delete.await_count == 3


async def test_delete_pattern_is_noop_with_warning(
    backend: MemcachedBackend, caplog: pytest.LogCaptureFixture
) -> None:
    """``delete_pattern`` логирует warning и не вызывает client."""
    with caplog.at_level(logging.WARNING):
        await backend.delete_pattern("any:*")
    backend._client.delete.assert_not_called()
    assert any("delete_pattern" in r.message for r in caplog.records)


async def test_exists_true(backend: MemcachedBackend) -> None:
    """``exists`` возвращает True если client.get вернул не None."""
    backend._client.get.return_value = b"x"
    assert await backend.exists("k") is True


async def test_exists_false(backend: MemcachedBackend) -> None:
    """``exists`` возвращает False если client.get вернул None."""
    backend._client.get.return_value = None
    assert await backend.exists("k") is False


async def test_close_delegates_to_client(backend: MemcachedBackend) -> None:
    """``close`` делегирует в client.close."""
    await backend.close()
    backend._client.close.assert_awaited_once()


def test_to_bytes_encodes_utf8() -> None:
    """``_to_bytes`` кодирует строку в UTF-8."""
    assert MemcachedBackend._to_bytes("hello") == b"hello"
    assert MemcachedBackend._to_bytes("ключ") == "ключ".encode("utf-8")
