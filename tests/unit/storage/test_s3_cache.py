"""
Тесты S3CacheAdapter.

Проверяют:
    * Первое чтение — S3 вызывается, кэш наполняется.
    * Повторное чтение — S3 НЕ вызывается, возвращается кэш.
    * put — S3.put_object + инвалидация Redis.
    * delete — S3.delete_object + инвалидация Redis.
    * TTL < 60 сек — кэширование отключается, каждый get идёт в S3.
    * Missing в S3 → None, кэш не наполняется.
"""

from __future__ import annotations

from typing import Any

from src.infrastructure.storage.s3_cache import S3CacheAdapter


class _FakeS3:
    """Fake S3 с in-memory хранилищем и счётчиком вызовов."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self.get_calls = 0
        self.put_calls = 0
        self.delete_calls = 0

    async def get_object_bytes(self, key: str) -> bytes | None:
        self.get_calls += 1
        return self._store.get(key)

    async def put_object(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> None:
        self.put_calls += 1
        self._store[key] = data

    async def delete_object(self, key: str) -> None:
        self.delete_calls += 1
        self._store.pop(key, None)


class _FakeCache:
    """Fake Redis с TTL-эмуляцией."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self.get_calls = 0
        self.set_calls = 0
        self.delete_calls = 0

    async def get(self, key: str) -> bytes | None:
        self.get_calls += 1
        return self._store.get(key)

    async def set(self, key: str, value: bytes, ex: int | None = None) -> Any:
        self.set_calls += 1
        self._store[key] = value

    async def delete(self, key: str) -> Any:
        self.delete_calls += 1
        self._store.pop(key, None)


async def test_first_get_fetches_from_s3_and_caches() -> None:
    """Первое чтение — S3 вызывается, кэш наполняется."""
    s3, cache = _FakeS3(), _FakeCache()
    await s3.put_object("reports/q1.pdf", b"pdf-bytes")
    s3.put_calls = 0  # сброс counter

    adapter = S3CacheAdapter(s3=s3, cache=cache, ttl_seconds=300)
    data = await adapter.get("reports/q1.pdf")

    assert data == b"pdf-bytes"
    assert s3.get_calls == 1
    assert cache.set_calls == 1


async def test_repeated_get_served_from_cache() -> None:
    """Повторное чтение не вызывает S3."""
    s3, cache = _FakeS3(), _FakeCache()
    await s3.put_object("reports/q1.pdf", b"pdf-bytes")
    s3.put_calls = 0

    adapter = S3CacheAdapter(s3=s3, cache=cache, ttl_seconds=300)
    await adapter.get("reports/q1.pdf")  # прогрев
    s3.get_calls = 0

    data = await adapter.get("reports/q1.pdf")  # должен идти только в кэш

    assert data == b"pdf-bytes"
    assert s3.get_calls == 0, "Повторный запрос не должен вызывать S3"


async def test_put_invalidates_cache() -> None:
    """put должен инвалидировать Redis-ключ."""
    s3, cache = _FakeS3(), _FakeCache()
    adapter = S3CacheAdapter(s3=s3, cache=cache, ttl_seconds=300)

    await adapter.put("x.txt", b"v1")
    await adapter.get("x.txt")  # наполнит кэш
    assert cache.set_calls == 1
    cache.delete_calls = 0  # сброс перед проверкой второй put

    await adapter.put("x.txt", b"v2")
    assert cache.delete_calls == 1


async def test_delete_invalidates_cache_and_s3() -> None:
    """delete удаляет из S3 и инвалидирует Redis."""
    s3, cache = _FakeS3(), _FakeCache()
    adapter = S3CacheAdapter(s3=s3, cache=cache, ttl_seconds=300)

    await adapter.put("x.txt", b"v1")
    await adapter.get("x.txt")
    cache.delete_calls = 0  # put уже инвалидировал — сбрасываем

    await adapter.delete("x.txt")
    assert s3.delete_calls == 1
    assert cache.delete_calls == 1
    assert await s3.get_object_bytes("x.txt") is None


async def test_low_ttl_disables_caching() -> None:
    """TTL < 60 сек → кэширование выключено, каждый get идёт в S3."""
    s3, cache = _FakeS3(), _FakeCache()
    await s3.put_object("x.txt", b"data")
    s3.put_calls = 0

    adapter = S3CacheAdapter(s3=s3, cache=cache, ttl_seconds=30)

    await adapter.get("x.txt")
    await adapter.get("x.txt")

    assert s3.get_calls == 2, "При отключённом кэше оба запроса идут в S3"
    assert cache.set_calls == 0, "Cache.set не должен вызываться"


async def test_missing_object_returns_none_and_does_not_cache() -> None:
    """Отсутствующий объект → None, кэш пустой."""
    s3, cache = _FakeS3(), _FakeCache()
    adapter = S3CacheAdapter(s3=s3, cache=cache, ttl_seconds=300)

    data = await adapter.get("not-exists.txt")

    assert data is None
    assert cache.set_calls == 0
