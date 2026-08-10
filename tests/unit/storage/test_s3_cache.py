"""Тесты S3CacheAdapter.

Проверяют:
    * Первое чтение — S3 вызывается, кэш наполняется.
    * Повторное чтение — S3 НЕ вызывается, возвращается кэш.
    * put — S3.put_object + инвалидация Redis.
    * delete — S3.delete_object + инвалидация Redis.
    * TTL < 60 сек — кэширование отключается, каждый get идёт в S3.
    * Missing в S3 → None, кэш не наполняется.
    * Cycle 35 B-03 storage: tenant prefix в cache keys
      (закрывает cache poisoning в storage layer).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.infrastructure.storage.s3_cache import S3CacheAdapter


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
        self, key: str, data: bytes, content_type: str | None = None,
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


# ── Cycle 35 B-03 storage: tenant prefix в cache keys ──────────


@pytest.fixture(autouse=True)
def _disable_tenant_cache_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing тесты НЕ ожидают tenant prefix (autouse = backward-compat).

    Cycle 35: feature flag default = True (production). Для существующих
    тестов отключаем префикс — поведение идентично pre-fix.
    """
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "tenant_cache_prefix_enabled", False)


def test_cache_key_includes_tenant_prefix_when_flag_on_and_tenant_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-03 storage: при flag=ON + tenant → ключ ``tenant:{id}:s3cache:{key}``."""
    from src.backend.core.config.features import feature_flags
    from src.backend.core.tenancy import TenantContext, _current

    monkeypatch.setattr(feature_flags, "tenant_cache_prefix_enabled", True)
    s3, cache = _FakeS3(), _FakeCache()
    adapter = S3CacheAdapter(s3=s3, cache=cache, ttl_seconds=300)

    token = _current.set(TenantContext(tenant_id="bank_a"))
    try:
        cache_key = adapter._cache_key("reports/q1.pdf")
    finally:
        _current.reset(token)

    assert cache_key == "tenant:bank_a:s3cache:reports/q1.pdf"


def test_cache_key_uses_unscoped_prefix_when_flag_on_but_no_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-03: при flag=ON без tenant → ``tenant:_unscoped_:s3cache:{key}`` (изоляция)."""
    from src.backend.core.config.features import feature_flags
    from src.backend.core.tenancy import _current

    monkeypatch.setattr(feature_flags, "tenant_cache_prefix_enabled", True)
    s3, cache = _FakeS3(), _FakeCache()
    adapter = S3CacheAdapter(s3=s3, cache=cache, ttl_seconds=300)

    try:
        token = _current.set(None)
    except LookupError:
        token = None
    try:
        cache_key = adapter._cache_key("data/x.csv")
    finally:
        if token is not None:
            _current.reset(token)

    # Unscoped tenant prefix изолирует ключи без tenant от scoped.
    assert cache_key == "tenant:_unscoped_:s3cache:data/x.csv"


def test_cache_key_no_prefix_when_flag_off() -> None:
    """B-03: при flag=OFF (autouse fixture) — backward-compat поведение.

    Cycle 35: pre-fix формат ``{key_prefix}{key}`` сохраняется когда
    feature flag выключен (test override / opt-out в production).
    """
    s3, cache = _FakeS3(), _FakeCache()
    adapter = S3CacheAdapter(s3=s3, cache=cache, ttl_seconds=300)

    cache_key = adapter._cache_key("data/x.csv")
    # No tenant prefix.
    assert cache_key == "s3cache:data/x.csv"


def test_cache_key_separates_tenants_under_same_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-03: разные tenants — разные Redis keys (cache isolation).

    Cycle 35: без tenant prefix, tenant A и tenant B могут
    перезаписывать друг друга в shared Redis cache. С prefix —
    ключи полностью изолированы.
    """
    from src.backend.core.config.features import feature_flags
    from src.backend.core.tenancy import TenantContext, _current

    monkeypatch.setattr(feature_flags, "tenant_cache_prefix_enabled", True)
    s3, cache = _FakeS3(), _FakeCache()
    adapter = S3CacheAdapter(s3=s3, cache=cache, ttl_seconds=300)

    # tenant A
    token_a = _current.set(TenantContext(tenant_id="bank_a"))
    try:
        key_a = adapter._cache_key("reports/x.pdf")
    finally:
        _current.reset(token_a)

    # tenant B
    token_b = _current.set(TenantContext(tenant_id="bank_b"))
    try:
        key_b = adapter._cache_key("reports/x.pdf")
    finally:
        _current.reset(token_b)

    # Разные keys для одного логического cache-key.
    assert key_a != key_b
    assert key_a == "tenant:bank_a:s3cache:reports/x.pdf"
    assert key_b == "tenant:bank_b:s3cache:reports/x.pdf"
