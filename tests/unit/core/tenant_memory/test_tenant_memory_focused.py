"""Focused tests for ``core.tenant_memory`` (Wave 3 #24)."""

from __future__ import annotations

import time

import pytest

from src.backend.core.tenant_memory import (
    MemoryAccessPolicy,
    MemoryEntry,
    TenantMemoryStore,
    get_memory_store,
)
from src.backend.core.tenant_memory.store import reset_memory_store


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_memory_store()


class TestMemoryEntry:
    def test_defaults(self) -> None:
        e = MemoryEntry(tenant_id="t1", key="k1", value=42)
        assert e.created_at == 0.0
        assert e.expires_at is None
        assert e.tags == ()
        assert e.is_expired() is False

    def test_with_expiry(self) -> None:
        e = MemoryEntry(
            tenant_id="t1", key="k1", value="v", expires_at=time.time() - 10
        )
        assert e.is_expired() is True

    def test_with_ttl(self) -> None:
        e = MemoryEntry(
            tenant_id="t1", key="k1", value="v", expires_at=time.time() + 100
        )
        assert e.is_expired() is False


class TestMemoryAccessPolicy:
    def test_defaults(self) -> None:
        p = MemoryAccessPolicy()
        assert p.allowed_tenants is None
        assert p.blocked_keys == ()
        assert p.read_only is False

    def test_custom(self) -> None:
        p = MemoryAccessPolicy(
            allowed_tenants=("t1", "t2"),
            blocked_keys=("secret.*",),
            read_only=True,
        )
        assert "t1" in p.allowed_tenants


class TestStoreInit:
    def test_init(self) -> None:
        s = TenantMemoryStore()
        assert s.size() == 0
        assert s.list_tenants() == []


class TestPutGet:
    def test_put_and_get(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "k1", "value1")
        assert s.get("t1", "k1") == "value1"

    def test_get_missing_raises(self) -> None:
        s = TenantMemoryStore()
        with pytest.raises(KeyError, match="not found"):
            s.get("t1", "missing")

    def test_try_get_default(self) -> None:
        s = TenantMemoryStore()
        assert s.try_get("t1", "missing", "default") == "default"
        assert s.try_get("t1", "missing") is None

    def test_try_get_existing(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "k1", "v1")
        assert s.try_get("t1", "k1") == "v1"
        assert s.try_get("t1", "k1", "default") == "v1"

    def test_put_overwrites(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "k1", "v1")
        s.put("t1", "k1", "v2")
        assert s.get("t1", "k1") == "v2"


class TestNamespaceIsolation:
    def test_tenant_isolation(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "shared_key", "t1_value")
        s.put("t2", "shared_key", "t2_value")
        assert s.get("t1", "shared_key") == "t1_value"
        assert s.get("t2", "shared_key") == "t2_value"

    def test_cross_tenant_get_raises(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "k1", "v1")
        # t2 tries to read t1's key → KeyError (no leak).
        with pytest.raises(KeyError):
            s.get("t2", "k1")

    def test_size_per_tenant(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "a", 1)
        s.put("t1", "b", 2)
        s.put("t2", "c", 3)
        assert s.tenant_size("t1") == 2
        assert s.tenant_size("t2") == 1

    def test_list_keys_per_tenant(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "a", 1)
        s.put("t1", "b", 2)
        s.put("t2", "c", 3)
        assert sorted(s.list_keys("t1")) == ["a", "b"]
        assert s.list_keys("t2") == ["c"]


class TestDelete:
    def test_delete_existing(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "k1", "v1")
        assert s.delete("t1", "k1") is True
        assert s.exists("t1", "k1") is False

    def test_delete_missing(self) -> None:
        s = TenantMemoryStore()
        assert s.delete("t1", "missing") is False

    def test_exists(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "k1", "v1")
        assert s.exists("t1", "k1") is True
        assert s.exists("t1", "missing") is False


class TestSearch:
    def test_search_glob(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "user.pref.theme", "dark")
        s.put("t1", "user.pref.lang", "ru")
        s.put("t1", "system.config", "x")
        results = s.search("t1", "user.pref.*")
        assert len(results) == 2

    def test_search_no_match(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "k1", "v1")
        assert s.search("t1", "nomatch.*") == []

    def test_search_isolated_to_tenant(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "key.1", "v1")
        s.put("t2", "key.1", "v2")
        t1 = s.search("t1", "*")
        t2 = s.search("t2", "*")
        assert len(t1) == 1
        assert len(t2) == 1
        assert t1[0].value == "v1"
        assert t2[0].value == "v2"


class TestBulkOps:
    def test_clear_tenant(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "a", 1)
        s.put("t1", "b", 2)
        s.put("t2", "c", 3)
        count = s.clear_tenant("t1")
        assert count == 2
        assert s.tenant_size("t1") == 0
        assert s.tenant_size("t2") == 1

    def test_clear_all(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "a", 1)
        s.put("t2", "b", 2)
        s.clear()
        assert s.size() == 0

    def test_cleanup_expired(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "k1", "v1", ttl_seconds=0.01)
        s.put("t1", "k2", "v2", ttl_seconds=100)
        time.sleep(0.05)
        count = s.cleanup_expired()
        assert count == 1
        assert s.exists("t1", "k1") is False
        assert s.exists("t1", "k2") is True


class TestTTL:
    def test_expired_entry_removed_on_get(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "k1", "v1", ttl_seconds=0.01)
        time.sleep(0.05)
        # Get returns KeyError because entry is expired.
        with pytest.raises(KeyError):
            s.get("t1", "k1")

    def test_expired_entry_not_in_list(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "k1", "v1", ttl_seconds=0.01)
        s.put("t1", "k2", "v2", ttl_seconds=100)
        time.sleep(0.05)
        keys = s.list_keys("t1")
        assert "k1" not in keys
        assert "k2" in keys


class TestPolicyAllowedTenants:
    def test_tenant_not_allowed(self) -> None:
        s = TenantMemoryStore(
            MemoryAccessPolicy(allowed_tenants=("t1", "t2"))
        )
        s.put("t1", "k1", "v1")
        # t3 not in allowlist → PermissionError.
        with pytest.raises(PermissionError):
            s.put("t3", "k1", "v1")
        with pytest.raises(PermissionError):
            s.get("t3", "k1")

    def test_tenant_allowed(self) -> None:
        s = TenantMemoryStore(
            MemoryAccessPolicy(allowed_tenants=("t1",))
        )
        s.put("t1", "k1", "v1")
        assert s.get("t1", "k1") == "v1"


class TestPolicyBlockedKeys:
    def test_blocked_key_on_put(self) -> None:
        s = TenantMemoryStore(
            MemoryAccessPolicy(blocked_keys=("secret.*",))
        )
        with pytest.raises(PermissionError, match="blocked"):
            s.put("t1", "secret.token", "value")

    def test_blocked_key_on_get(self) -> None:
        s = TenantMemoryStore(
            MemoryAccessPolicy(blocked_keys=("secret.*",))
        )
        s.put("t1", "normal.key", "v1")
        with pytest.raises(PermissionError):
            s.put("t1", "secret.token", "v1")

    def test_pattern_glob(self) -> None:
        s = TenantMemoryStore(
            MemoryAccessPolicy(blocked_keys=("*.password", "*.token"))
        )
        with pytest.raises(PermissionError):
            s.put("t1", "user.password", "v1")
        with pytest.raises(PermissionError):
            s.put("t1", "service.token", "v1")
        # Allowed.
        s.put("t1", "user.name", "v1")


class TestPolicyReadOnly:
    def test_read_only_blocks_put(self) -> None:
        s = TenantMemoryStore(MemoryAccessPolicy(read_only=True))
        with pytest.raises(PermissionError, match="read-only"):
            s.put("t1", "k1", "v1")

    def test_read_only_allows_get(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "k1", "v1")
        s.set_policy(MemoryAccessPolicy(read_only=True))
        # Get still works.
        assert s.get("t1", "k1") == "v1"

    def test_read_only_blocks_clear(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "k1", "v1")
        s.set_policy(MemoryAccessPolicy(read_only=True))
        with pytest.raises(PermissionError):
            s.clear_tenant("t1")


class TestPolicySet:
    def test_set_policy_at_runtime(self) -> None:
        s = TenantMemoryStore()
        s.put("t1", "k1", "v1")
        # Initially allows all.
        assert s.get("t1", "k1") == "v1"
        # Now restrict.
        s.set_policy(MemoryAccessPolicy(allowed_tenants=("t1",)))
        assert s.get("t1", "k1") == "v1"  # still works for t1
        with pytest.raises(PermissionError):
            s.get("t2", "k1")


class TestSingleton:
    def test_singleton(self) -> None:
        s1 = get_memory_store()
        s2 = get_memory_store()
        assert s1 is s2

    def test_reset(self) -> None:
        s1 = get_memory_store()
        reset_memory_store()
        s2 = get_memory_store()
        assert s1 is not s2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import tenant_memory

        assert len(tenant_memory.__all__) == 4


class TestRealisticExample:
    """Realistic: per-tenant AI agent memory with policy."""

    def test_agent_memory_isolation(self) -> None:
        store = TenantMemoryStore(
            MemoryAccessPolicy(
                allowed_tenants=("bank-t1", "bank-t2"),
                blocked_keys=("secret.*", "credentials.*"),
            )
        )
        # Each tenant has own user preferences.
        store.put("bank-t1", "user_pref.theme", "dark")
        store.put("bank-t1", "user_pref.lang", "ru")
        store.put("bank-t2", "user_pref.theme", "light")

        # Tenant t1 sees only own prefs.
        t1_keys = sorted(store.list_keys("bank-t1"))
        assert t1_keys == ["user_pref.lang", "user_pref.theme"]
        assert store.get("bank-t1", "user_pref.theme") == "dark"

        # Tenant t2 sees own.
        assert store.get("bank-t2", "user_pref.theme") == "light"

        # Cross-tenant → KeyError.
        with pytest.raises(KeyError):
            store.get("bank-t1", "user_pref")  # t1 doesn't have this key
        # t1's values don't leak to t2.
        t2_t1_value = store.try_get("bank-t2", "user_pref.theme")
        assert t2_t1_value == "light"  # not "dark"

        # Blocked keys → no put.
        with pytest.raises(PermissionError):
            store.put("bank-t1", "secret.api_token", "abc123")

        # Cleanup expired.
        store.put("bank-t1", "session.token", "xyz", ttl_seconds=0.01)
        time.sleep(0.05)
        removed = store.cleanup_expired()
        assert removed == 1
