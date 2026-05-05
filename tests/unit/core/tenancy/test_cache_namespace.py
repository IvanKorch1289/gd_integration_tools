# ruff: noqa: S101
"""Тесты `TenantNamespacedCache` (R2.4): изоляция между tenants."""

from __future__ import annotations

import pytest

from src.core.interfaces.cache import CacheBackend
from src.core.tenancy import TenantContext, tenant_scope
from src.core.tenancy.cache import (
    DEFAULT_TENANT_PREFIX,
    TenantNamespacedCache,
    build_tenant_key,
)


class _MemBackend(CacheBackend):
    """In-memory backend для тестов."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self.store.pop(k, None)

    async def delete_pattern(self, pattern: str) -> None:
        # Простейшее prefix-сопоставление (pattern без `*` — exact;
        # с `*` на конце — startswith).
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            for k in [k for k in self.store if k.startswith(prefix)]:
                self.store.pop(k, None)
        elif pattern in self.store:
            self.store.pop(pattern, None)

    async def exists(self, key: str) -> bool:
        return key in self.store


class TestBuildTenantKey:
    def test_explicit_tenant(self) -> None:
        assert build_tenant_key("foo", tenant_id="bank-a") == "tenant:bank-a:foo"

    def test_no_context_falls_back_to_default(self) -> None:
        assert build_tenant_key("foo") == f"tenant:{DEFAULT_TENANT_PREFIX}:foo"

    def test_uses_context_when_set(self) -> None:
        with tenant_scope(TenantContext(tenant_id="bank-b")):
            assert build_tenant_key("foo") == "tenant:bank-b:foo"


@pytest.mark.asyncio
class TestTenantNamespacedCacheBasic:
    async def test_set_get_uses_prefix(self) -> None:
        inner = _MemBackend()
        cache = TenantNamespacedCache(inner, tenant_id="bank-a")
        await cache.set("k", b"v")
        assert "tenant:bank-a:k" in inner.store
        assert "k" not in inner.store
        assert await cache.get("k") == b"v"

    async def test_get_unknown_key_returns_none(self) -> None:
        inner = _MemBackend()
        cache = TenantNamespacedCache(inner, tenant_id="bank-a")
        assert await cache.get("missing") is None

    async def test_delete_specific_keys(self) -> None:
        inner = _MemBackend()
        cache = TenantNamespacedCache(inner, tenant_id="t")
        await cache.set("a", b"1")
        await cache.set("b", b"2")
        await cache.delete("a", "b")
        assert inner.store == {}

    async def test_exists(self) -> None:
        inner = _MemBackend()
        cache = TenantNamespacedCache(inner, tenant_id="t")
        await cache.set("k", b"v")
        assert await cache.exists("k") is True
        assert await cache.exists("missing") is False


@pytest.mark.asyncio
class TestTenantIsolation:
    """Property: ключ одного tenant не виден другому tenant."""

    async def test_two_tenants_dont_see_each_other(self) -> None:
        inner = _MemBackend()
        cache_a = TenantNamespacedCache(inner, tenant_id="bank-a")
        cache_b = TenantNamespacedCache(inner, tenant_id="bank-b")

        await cache_a.set("balance", b"100")
        await cache_b.set("balance", b"200")

        assert await cache_a.get("balance") == b"100"
        assert await cache_b.get("balance") == b"200"

    async def test_delete_pattern_scoped_to_tenant(self) -> None:
        inner = _MemBackend()
        cache_a = TenantNamespacedCache(inner, tenant_id="bank-a")
        cache_b = TenantNamespacedCache(inner, tenant_id="bank-b")

        await cache_a.set("k1", b"a1")
        await cache_a.set("k2", b"a2")
        await cache_b.set("k1", b"b1")

        await cache_a.delete_pattern("*")  # удалить всё в namespace A

        # Bank A пусто, bank B сохранён.
        assert await cache_a.get("k1") is None
        assert await cache_a.get("k2") is None
        assert await cache_b.get("k1") == b"b1"

    async def test_dynamic_resolution_via_contextvar(self) -> None:
        inner = _MemBackend()
        cache = TenantNamespacedCache(inner)  # без фиксированного tenant_id

        with tenant_scope(TenantContext(tenant_id="t1")):
            await cache.set("k", b"v1")
        with tenant_scope(TenantContext(tenant_id="t2")):
            await cache.set("k", b"v2")

        # Оба значения хранятся отдельно.
        with tenant_scope(TenantContext(tenant_id="t1")):
            assert await cache.get("k") == b"v1"
        with tenant_scope(TenantContext(tenant_id="t2")):
            assert await cache.get("k") == b"v2"

    async def test_empty_delete_is_noop(self) -> None:
        inner = _MemBackend()
        cache = TenantNamespacedCache(inner, tenant_id="t")
        await cache.set("k", b"v")
        await cache.delete()  # пустой *keys
        assert await cache.get("k") == b"v"
