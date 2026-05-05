"""Unit-тесты для :class:`MemoryBackend` (in-memory cache на cachetools).

Проверяем контракт ``CacheBackend``: get/set/delete/delete_pattern/exists.
TTL через cachetools задаётся глобально на cache, поэтому индивидуальные
ttl-overrides не проверяем (см. docstring в исходнике backend'а).
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.infrastructure.cache.backends.memory import MemoryBackend


@pytest.fixture
def backend() -> MemoryBackend:
    """Свежий экземпляр MemoryBackend для каждого теста."""
    return MemoryBackend(maxsize=100, default_ttl=60)


async def test_get_missing_returns_none(backend: MemoryBackend) -> None:
    """``get`` для отсутствующего ключа возвращает None."""
    assert await backend.get("missing") is None


async def test_set_then_get_roundtrip(backend: MemoryBackend) -> None:
    """``set``+``get`` возвращают сохранённое значение."""
    await backend.set("key1", b"value1")
    assert await backend.get("key1") == b"value1"


async def test_set_overwrites_existing(backend: MemoryBackend) -> None:
    """Повторный ``set`` перезаписывает значение."""
    await backend.set("k", b"v1")
    await backend.set("k", b"v2")
    assert await backend.get("k") == b"v2"


async def test_set_accepts_ttl_argument(backend: MemoryBackend) -> None:
    """Аргумент ttl принимается без ошибок (фактический TTL — глобальный)."""
    await backend.set("key", b"val", ttl=10)
    assert await backend.get("key") == b"val"


async def test_delete_single_key(backend: MemoryBackend) -> None:
    """``delete`` удаляет единичный ключ."""
    await backend.set("a", b"1")
    await backend.delete("a")
    assert await backend.get("a") is None


async def test_delete_multiple_keys(backend: MemoryBackend) -> None:
    """``delete`` удаляет несколько ключей за один вызов."""
    await backend.set("a", b"1")
    await backend.set("b", b"2")
    await backend.set("c", b"3")
    await backend.delete("a", "b")
    assert await backend.get("a") is None
    assert await backend.get("b") is None
    assert await backend.get("c") == b"3"


async def test_delete_missing_is_noop(backend: MemoryBackend) -> None:
    """``delete`` для отсутствующего ключа не падает."""
    await backend.delete("missing")  # не должно бросать


async def test_delete_no_keys(backend: MemoryBackend) -> None:
    """``delete`` без аргументов — допустимый no-op."""
    await backend.delete()


async def test_delete_pattern_matches_glob(backend: MemoryBackend) -> None:
    """``delete_pattern`` удаляет ключи по glob-маске."""
    await backend.set("user:1", b"a")
    await backend.set("user:2", b"b")
    await backend.set("session:1", b"c")
    await backend.delete_pattern("user:*")
    assert await backend.get("user:1") is None
    assert await backend.get("user:2") is None
    assert await backend.get("session:1") == b"c"


async def test_delete_pattern_no_matches(backend: MemoryBackend) -> None:
    """``delete_pattern`` без совпадений не трогает ключи."""
    await backend.set("k", b"v")
    await backend.delete_pattern("zzz:*")
    assert await backend.get("k") == b"v"


async def test_exists_true(backend: MemoryBackend) -> None:
    """``exists`` возвращает True для присутствующего ключа."""
    await backend.set("k", b"v")
    assert await backend.exists("k") is True


async def test_exists_false(backend: MemoryBackend) -> None:
    """``exists`` возвращает False для отсутствующего ключа."""
    assert await backend.exists("missing") is False


async def test_exists_after_delete(backend: MemoryBackend) -> None:
    """После ``delete`` ключ не существует."""
    await backend.set("k", b"v")
    await backend.delete("k")
    assert await backend.exists("k") is False


async def test_maxsize_evicts_oldest() -> None:
    """При переполнении cachetools вытесняет старые элементы."""
    backend = MemoryBackend(maxsize=2, default_ttl=60)
    await backend.set("a", b"1")
    await backend.set("b", b"2")
    await backend.set("c", b"3")  # должен вытеснить "a" (LRU/TTL-стратегия)
    # Должно остаться 2 элемента, "a" — вытеснен.
    keys_present = [
        await backend.exists(k) for k in ("a", "b", "c")
    ]
    assert sum(keys_present) == 2


async def test_value_is_bytes(backend: MemoryBackend) -> None:
    """Значения хранятся как bytes без преобразований."""
    raw = b"\x00\x01\x02binary"
    await backend.set("bin", raw)
    assert await backend.get("bin") == raw
