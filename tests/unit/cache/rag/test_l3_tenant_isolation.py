"""Sprint 2.1 (L5 RAG/Memory tenant-scope) — cross-tenant isolation regression tests.

Покрытие:
    * L3RetrievalCache ключи tenant-aware: ключ включает tenant_id,
      изоляция между tenant A и tenant B гарантирована.
    * Версионированный namespace ``v2`` — backward-compat: legacy-ключи
      ``rag:l3:*`` (без tenant) больше не достижимы, новые пишутся
      под ``rag:l3:v2:*`` (collision невозможен).
    * Sentinel ``_unscoped_`` — вызов без tenant пишет в изолированный
      unscope-namespace, а не смешивает с tenant-scoped ключами.
    * ThreeTierRagCache.lookup_chunks / store_chunks пробрасывают tenant
      в L3 (consistent с L1/L2 ветками).
    * Namespace + tenant комбинируются без коллизий.
    * invalidate() учитывает tenant (invalidate tenant A не трогает tenant B).
    * flush() с версионированным prefix безопасен (только v2-prefix).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import orjson
import pytest

from src.backend.infrastructure.cache.rag.retrieval import L3RetrievalCache
from src.backend.infrastructure.cache.rag.three_tier import ThreeTierRagCache


class _FakeRedis:
    """In-memory fake Redis с tenant-aware scan/unlink."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.cache_get = AsyncMock(side_effect=self._cget)
        self.cache_set = AsyncMock(side_effect=self._cset)
        self.cache_delete = AsyncMock(side_effect=self._cdel)

    async def _cget(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def _cset(self, key: str, value: bytes, ttl: int) -> None:
        self.store[key] = value

    async def _cdel(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                deleted += 1
        return deleted

    async def execute(self, kind: str, op: Any) -> Any:
        """Имитация execute('cache', op) — flush scanner."""

        class _Conn:
            def __init__(self_outer: "_Conn", outer: _FakeRedis) -> None:
                self_outer._outer = outer

            async def scan_iter(self_outer: "_Conn", match: str, count: int) -> Any:
                for k in list(self_outer._outer.store.keys()):
                    if _glob_match(k, match):
                        yield k

            async def unlink(self_outer: "_Conn", *keys: str) -> int:
                n = 0
                for k in keys:
                    if k in self_outer._outer.store:
                        del self_outer._outer.store[k]
                        n += 1
                return n

        return await op(_Conn(self))


def _glob_match(key: str, pattern: str) -> bool:
    """Минимальный fnmatch-аналог: поддержка ``*``."""
    import fnmatch

    return fnmatch.fnmatch(key, pattern)


def _make_cache() -> tuple[L3RetrievalCache, _FakeRedis]:
    redis = _FakeRedis()
    cache = L3RetrievalCache(redis_client=redis, ttl_seconds=60)
    return cache, redis


# === L3RetrievalCache: ключи и формат ============================


def test_l3_prefix_is_versioned_v2() -> None:
    """Sprint 2.1: PREFIX версионирован ``rag:l3:v2:`` для backward-compat."""
    assert L3RetrievalCache.PREFIX == "rag:l3:v2:"


def test_l3_key_includes_tenant_and_namespace() -> None:
    """Ключ включает tenant_id и namespace — collision невозможен."""
    cache, _ = _make_cache()
    key = cache._key("Q", tenant="bank_a", namespace="ns_x")
    assert key.startswith("rag:l3:v2:tenant:bank_a:ns_x:")
    digest = key.split(":")[-1]
    assert len(digest) == 64  # sha256 hex


def test_l3_key_uses_unscoped_sentinel_for_missing_tenant() -> None:
    """Без tenant — sentinel ``_unscoped_`` (consistent с TenantCacheBackend)."""
    cache, _ = _make_cache()
    key = cache._key("Q", namespace="ns_x")
    assert "tenant:_unscoped_:ns_x:" in key


def test_l3_key_uses_global_sentinel_for_missing_namespace() -> None:
    """Без namespace — sentinel ``_global_`` (однозначный парсинг)."""
    cache, _ = _make_cache()
    key_a = cache._key("Q", tenant="bank_a")
    key_b = cache._key("Q", tenant="bank_a")
    assert key_a == key_b
    assert "tenant:bank_a:_global_:" in key_a


def test_l3_key_different_tenants_no_collision() -> None:
    """Два tenant-а с одинаковыми query/namespace дают разные ключи."""
    cache, _ = _make_cache()
    k_a = cache._key("одинаковый query", tenant="bank_a", namespace="ns")
    k_b = cache._key("одинаковый query", tenant="bank_b", namespace="ns")
    assert k_a != k_b
    assert "tenant:bank_a:" in k_a
    assert "tenant:bank_b:" in k_b


def test_l3_key_tenant_scope_isolated_from_unscoped() -> None:
    """Tenant-scoped ключ НИКОГДА не совпадает с unscoped ключом."""
    cache, _ = _make_cache()
    k_tenant = cache._key("Q", tenant="bank_a", namespace="ns")
    k_unscoped = cache._key("Q", namespace="ns")
    assert k_tenant != k_unscoped
    assert "tenant:bank_a:" in k_tenant
    assert "tenant:_unscoped_:" in k_unscoped


def test_l3_key_query_change_changes_digest() -> None:
    """Изменение query → изменение digest (как и раньше)."""
    cache, _ = _make_cache()
    k1 = cache._key("hello", tenant="a", namespace="ns")
    k2 = cache._key("hello world", tenant="a", namespace="ns")
    assert k1 != k2


# === L3RetrievalCache: roundtrip + cross-tenant isolation =========


@pytest.mark.asyncio
async def test_l3_cross_tenant_isolation_roundtrip() -> None:
    """Sprint 2.1: ключевой regression — tenant B не видит данные tenant A."""
    cache, redis = _make_cache()
    chunks_a = [{"document": "tenant-a-secret", "score": 0.9}]
    chunks_b = [{"document": "tenant-b-public", "score": 0.8}]

    await cache.set("Q", chunks_a, tenant="bank_a", namespace="ns")
    await cache.set("Q", chunks_b, tenant="bank_b", namespace="ns")

    got_a = await cache.get("Q", tenant="bank_a", namespace="ns")
    got_b = await cache.get("Q", tenant="bank_b", namespace="ns")
    assert got_a == chunks_a
    assert got_b == chunks_b


@pytest.mark.asyncio
async def test_l3_tenant_cannot_read_unscoped() -> None:
    """Tenant-scoped get видит miss при наличии unscoped-записи."""
    cache, _ = _make_cache()
    await cache.set("Q", [{"document": "unscoped"}], namespace="ns")
    leak = await cache.get("Q", tenant="bank_a", namespace="ns")
    assert leak is None


@pytest.mark.asyncio
async def test_l3_unscoped_get_misses_when_tenant_written() -> None:
    """Unscoped get видит miss при наличии tenant-scoped-записи."""
    cache, _ = _make_cache()
    await cache.set("Q", [{"document": "tenant-a"}], tenant="bank_a", namespace="ns")
    leak = await cache.get("Q", namespace="ns")
    assert leak is None


@pytest.mark.asyncio
async def test_l3_invalidate_tenant_specific() -> None:
    """invalidate tenant A не трогает tenant B."""
    cache, _ = _make_cache()
    await cache.set("Q", [{"document": "a"}], tenant="bank_a", namespace="ns")
    await cache.set("Q", [{"document": "b"}], tenant="bank_b", namespace="ns")

    await cache.invalidate("Q", tenant="bank_a", namespace="ns")

    assert await cache.get("Q", tenant="bank_a", namespace="ns") is None
    assert await cache.get("Q", tenant="bank_b", namespace="ns") == [{"document": "b"}]


@pytest.mark.asyncio
async def test_l3_set_uses_versioned_v2_prefix_in_redis() -> None:
    """Sprint 2.1: ровно v2-prefix попадает в Redis (старый ``rag:l3:`` — нет)."""
    cache, redis = _make_cache()
    await cache.set("Q", [{"document": "x"}], tenant="bank_a", namespace="ns")
    stored_keys = list(redis.store.keys())
    assert len(stored_keys) == 1
    assert stored_keys[0].startswith("rag:l3:v2:")
    # Legacy prefix ``rag:l3:`` (без ``v2:``) не должен появиться.
    assert not any(k.startswith("rag:l3:tenant:") for k in stored_keys)


@pytest.mark.asyncio
async def test_l3_set_serialization_preserves_chunks() -> None:
    """Сохранение/восстановление илиjson сохраняет точную структуру."""
    cache, redis = _make_cache()
    chunks = [
        {"document": "ctx", "score": 0.95, "metadata": {"doc_id": "d1", "chunk_idx": 0}},
    ]
    await cache.set("Q", chunks, tenant="bank_a", namespace="ns")
    # Прочитать прямо из Redis (bypass API) — payload должен быть orjson.
    raw = next(iter(redis.store.values()))
    assert raw == orjson.dumps(chunks)


@pytest.mark.asyncio
async def test_l3_get_decode_error_returns_none() -> None:
    """Если в Redis невалидный JSON — get возвращает None (не raise)."""
    cache, redis = _make_cache()
    # Записываем «мусор» напрямую в key-формате L3.
    key = cache._key("Q", tenant="bank_a", namespace="ns")
    redis.store[key] = b"not-valid-json"
    result = await cache.get("Q", tenant="bank_a", namespace="ns")
    assert result is None


@pytest.mark.asyncio
async def test_l3_get_non_list_payload_returns_none() -> None:
    """Если payload — не list (скажем, dict) — get возвращает None."""
    cache, redis = _make_cache()
    key = cache._key("Q", tenant="bank_a", namespace="ns")
    redis.store[key] = orjson.dumps({"unexpected": "object"})
    result = await cache.get("Q", tenant="bank_a", namespace="ns")
    assert result is None


@pytest.mark.asyncio
async def test_l3_namespace_partition_per_tenant() -> None:
    """Namespace + tenant комбинируются: разные namespace не пересекаются."""
    cache, _ = _make_cache()
    await cache.set("Q", [{"document": "ns1"}], tenant="bank_a", namespace="ns1")
    await cache.set("Q", [{"document": "ns2"}], tenant="bank_a", namespace="ns2")

    assert await cache.get("Q", tenant="bank_a", namespace="ns1") == [{"document": "ns1"}]
    assert await cache.get("Q", tenant="bank_a", namespace="ns2") == [{"document": "ns2"}]


# === L3RetrievalCache: flush =====================================


@pytest.mark.asyncio
async def test_l3_flush_only_v2_prefix() -> None:
    """flush() удаляет только v2-prefix; legacy ``rag:l3:*`` остаются."""
    cache, redis = _make_cache()
    redis.store["rag:l3:legacy:foo"] = b"old"
    redis.store["rag:l3:v2:tenant:bank_a:ns:digest"] = b"new"
    await cache.set("Q", [{"document": "x"}], tenant="bank_a", namespace="ns")

    n = await cache.flush()
    assert n >= 1  # все v2-prefix удалены
    assert "rag:l3:legacy:foo" in redis.store  # legacy — не тронут
    assert "rag:l3:v2:tenant:bank_a:ns:digest" not in redis.store


# === ThreeTierRagCache: tenant пробрасывается в L3 ================


@pytest.mark.asyncio
async def test_three_tier_lookup_chunks_passes_tenant_to_l3() -> None:
    """ThreeTierRagCache.lookup_chunks пробрасывает tenant в L3.get()."""
    l3 = AsyncMock()
    l3.get = AsyncMock(return_value=[{"document": "c"}])
    l3.set = AsyncMock()
    l3.flush = AsyncMock(return_value=0)
    cache = ThreeTierRagCache(l3=l3, l1_enabled=False, l2_enabled=False, l3_enabled=True)
    chunks, tier = await cache.lookup_chunks("Q", tenant="bank_a", namespace="ns")
    assert tier == "l3"
    assert chunks == [{"document": "c"}]
    l3.get.assert_awaited_once_with("Q", tenant="bank_a", namespace="ns")


@pytest.mark.asyncio
async def test_three_tier_store_chunks_passes_tenant_to_l3() -> None:
    """ThreeTierRagCache.store_chunks пробрасывает tenant в L3.set()."""
    l3 = AsyncMock()
    l3.set = AsyncMock()
    l3.flush = AsyncMock(return_value=0)
    cache = ThreeTierRagCache(l3=l3, l1_enabled=False, l2_enabled=False, l3_enabled=True)
    await cache.store_chunks("Q", [{"document": "c"}], tenant="bank_a", namespace="ns")
    l3.set.assert_awaited_once_with(
        "Q", [{"document": "c"}], tenant="bank_a", namespace="ns"
    )


@pytest.mark.asyncio
async def test_three_tier_lookup_chunks_backward_compat_without_tenant() -> None:
    """Sprint 2.1: backward-compat — вызов без tenant работает (default None)."""
    l3 = AsyncMock()
    l3.get = AsyncMock(return_value=None)
    l3.set = AsyncMock()
    l3.flush = AsyncMock(return_value=0)
    cache = ThreeTierRagCache(l3=l3, l1_enabled=False, l2_enabled=False, l3_enabled=True)
    chunks, tier = await cache.lookup_chunks("Q", namespace="legacy-ns")
    assert chunks is None
    assert tier is None
    l3.get.assert_awaited_once_with("Q", tenant=None, namespace="legacy-ns")


@pytest.mark.asyncio
async def test_three_tier_store_chunks_backward_compat_without_tenant() -> None:
    """Sprint 2.1: backward-compat — store_chunks без tenant (default None)."""
    l3 = AsyncMock()
    l3.set = AsyncMock()
    l3.flush = AsyncMock(return_value=0)
    cache = ThreeTierRagCache(l3=l3, l1_enabled=False, l2_enabled=False, l3_enabled=True)
    await cache.store_chunks("Q", [{"document": "c"}], namespace="legacy-ns")
    l3.set.assert_awaited_once_with(
        "Q", [{"document": "c"}], tenant=None, namespace="legacy-ns"
    )


@pytest.mark.asyncio
async def test_three_tier_lookup_chunks_disabled_returns_none() -> None:
    """При l3_enabled=False tenant не важен — короткий circuit."""
    l3 = AsyncMock()
    l3.get = AsyncMock()
    l3.set = AsyncMock()
    l3.flush = AsyncMock(return_value=0)
    cache = ThreeTierRagCache(l3=l3, l1_enabled=False, l2_enabled=False, l3_enabled=False)
    chunks, tier = await cache.lookup_chunks("Q", tenant="bank_a", namespace="ns")
    assert chunks is None
    assert tier is None
    l3.get.assert_not_called()
