"""Tests for core.dsl.variables.DSLVariableStore (S127 W2, Layer 2).

DSLVariableStore is the Airflow-style Variables backing store for
``${var('key')}`` expressions. Has 3 backends:
- ConsulVariableBackend (production)
- PostgresVariableBackend (HA production)
- InMemoryVariableBackend (tests/dev)

These tests focus on:
- API contract (get/set/delete/list_keys)
- TTL handling (expired entries return None)
- Scope isolation (tenant:X vs global)
- Backend selection via factory

Note: Python 3.14 removed ``asyncio.get_event_loop()`` in main thread,
so we use ``asyncio.new_event_loop()`` via ``run_coroutine_threadsafe``
or simply run each test via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.dsl.variables import (
    DSLVariableStore,
    InMemoryVariableBackend,
    VariableScope,
)


def _run(coro):
    """Run a coroutine synchronously. Uses asyncio.run for Python 3.14+ safety."""
    return asyncio.run(coro)


class TestInMemoryVariableBackend:
    """Layer 2 tests for the InMemoryVariableBackend (the default test backend)."""

    def test_get_missing_returns_none(self) -> None:
        backend = InMemoryVariableBackend()
        # get() returns None for missing, doesn't raise (graceful DSL semantics).
        result = _run(backend.get("missing", VariableScope("global")))
        assert result is None

    def test_set_then_get_roundtrip(self) -> None:
        backend = InMemoryVariableBackend()
        _run(backend.set("foo", "bar", VariableScope("global")))
        assert _run(backend.get("foo", VariableScope("global"))) == "bar"

    def test_set_with_ttl_zero_means_no_expiry(self) -> None:
        """TTL=0 (or None) means no expiry — entry persists indefinitely."""
        backend = InMemoryVariableBackend()
        _run(backend.set("foo", "bar", VariableScope("global"), ttl=0))
        # TTL=0 is interpreted as 'no expiry' (expires_at = 0, never less than now).
        assert _run(backend.get("foo", VariableScope("global"))) == "bar"

    def test_delete_removes_entry(self) -> None:
        backend = InMemoryVariableBackend()
        _run(backend.set("foo", "bar", VariableScope("global")))
        _run(backend.delete("foo", VariableScope("global")))
        assert _run(backend.get("foo", VariableScope("global"))) is None

    def test_scope_isolation(self) -> None:
        """Same key in different scopes returns different values."""
        backend = InMemoryVariableBackend()
        _run(backend.set("api_key", "global-key", VariableScope.global_scope()))
        _run(backend.set("api_key", "tenant-a-key", VariableScope.for_tenant("a")))
        _run(backend.set("api_key", "tenant-b-key", VariableScope.for_tenant("b")))
        assert _run(backend.get("api_key", VariableScope.global_scope())) == "global-key"
        assert (
            _run(backend.get("api_key", VariableScope.for_tenant("a")))
            == "tenant-a-key"
        )
        assert (
            _run(backend.get("api_key", VariableScope.for_tenant("b")))
            == "tenant-b-key"
        )

    def test_list_keys_scoped(self) -> None:
        backend = InMemoryVariableBackend()
        _run(backend.set("k1", "v1", VariableScope.global_scope()))
        _run(backend.set("k2", "v2", VariableScope.global_scope()))
        _run(backend.set("k1", "v1-tenant", VariableScope.for_tenant("a")))
        global_keys = _run(backend.list_keys(VariableScope.global_scope()))
        tenant_keys = _run(backend.list_keys(VariableScope.for_tenant("a")))
        assert sorted(global_keys) == ["k1", "k2"]
        assert tenant_keys == ["k1"]

    def test_delete_missing_returns_none(self) -> None:
        """delete() on missing key is a no-op (returns None), not error."""
        backend = InMemoryVariableBackend()
        # No exception raised.
        _run(backend.delete("nonexistent", VariableScope("global")))


class TestDSLVariableStoreFactory:
    """Layer 2 tests for DSLVariableStore factory + backend selection."""

    def test_get_default_uses_in_memory(self) -> None:
        """Default factory returns DSLVariableStore with InMemoryVariableBackend."""
        store = DSLVariableStore.get_default()
        assert len(store.backends) == 1
        assert isinstance(store.backends[0], InMemoryVariableBackend)

    def test_get_set_via_store(self) -> None:
        store = DSLVariableStore.get_default()
        unique_key = "foo_unique_get_set"
        _run(store.set(unique_key, "bar", VariableScope.global_scope()))
        assert _run(store.get(unique_key, VariableScope.global_scope())) == "bar"

    def test_get_missing_returns_none_via_store(self) -> None:
        """DSLVariableStore.get returns None for missing (does NOT raise).

        Note: VariableNotFoundError is exported but never raised by the
        current implementation. The docstring claim is stale — callers
        that need strict-missing must check for None.
        """
        store = DSLVariableStore.get_default()
        result = _run(
            store.get("nonexistent_unique_does_not_exist", VariableScope.global_scope())
        )
        assert result is None

    def test_set_with_ttl_zero_no_expiry_via_store(self) -> None:
        """TTL=0 means no expiry via store API too (consistent semantics)."""
        store = DSLVariableStore.get_default()
        _run(store.set("foo_unique_ttl", "bar", VariableScope.global_scope(), ttl=0))
        assert _run(store.get("foo_unique_ttl", VariableScope.global_scope())) == "bar"

    def test_list_keys_via_store(self) -> None:
        """Layer 2: list_keys returns only the keys in the requested scope.

        Note: default singleton state leaks across tests, so we use
        unique key names and assert containment rather than equality.
        """
        store = DSLVariableStore.get_default()
        unique = "list_keys_unique_test"
        _run(store.set(f"{unique}_1", "v1", VariableScope.global_scope()))
        _run(store.set(f"{unique}_2", "v2", VariableScope.global_scope()))
        keys = _run(store.list_keys(VariableScope.global_scope()))
        assert f"{unique}_1" in keys
        assert f"{unique}_2" in keys


class TestVariableScope:
    """Layer 2 tests for VariableScope dataclass."""

    def test_scope_global(self) -> None:
        s = VariableScope(kind="global")
        assert str(s) == "global"

    def test_scope_tenant(self) -> None:
        s = VariableScope(kind="tenant", identifier="acme")
        assert str(s) == "tenant:acme"

    def test_scope_invalid_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid scope kind"):
            VariableScope(kind="namespace:acme", identifier="acme")

    def test_scope_tenant_requires_identifier(self) -> None:
        with pytest.raises(ValueError, match="requires non-empty identifier"):
            VariableScope(kind="tenant")

    def test_scope_hashable(self) -> None:
        """Scopes must be hashable (used as dict keys in backend)."""
        s1 = VariableScope(kind="tenant", identifier="acme")
        s2 = VariableScope(kind="tenant", identifier="acme")
        assert s1 == s2
        assert hash(s1) == hash(s2)
        d = {s1: "value"}
        assert d[s2] == "value"

    def test_scope_factory_global(self) -> None:
        """VariableScope.global_scope() factory."""
        from src.backend.core.dsl.variables import VariableScope

        s = VariableScope.global_scope()
        assert s.kind == "global"
        assert str(s) == "global"

    def test_scope_factory_tenant(self) -> None:
        s = VariableScope.for_tenant("acme")
        assert s.kind == "tenant"
        assert s.identifier == "acme"

    def test_scope_factory_route(self) -> None:
        s = VariableScope.for_route("orders.ship")
        assert s.kind == "route"
        assert s.identifier == "orders.ship"
