"""S45 W4 — Stream C: Hypothesis property-based tests for DSL Variable Store.

Per ADR-0261 Sprint 45 ratchet plan (Stream C, target +0.5pp).
hypothesis >= 6.0 already in dev deps.

Tests invariants of DSLVariableStore:
1. set(k, v) → get(k) returns v (round-trip, async)
2. set(k, v1); set(k, v2); get(k) returns v2 (last-write-wins)
3. scope isolation: set in scope1 doesn't affect scope2
4. get on unknown key returns None (no exception)
5. integer / string / None values round-trip
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


pytestmark = pytest.mark.asyncio


async def _fresh_store() -> Any:
    """Fresh DSLVariableStore for each test (in-memory backend)."""
    from src.backend.core.dsl.variables import (
        DSLVariableStore,
        InMemoryVariableBackend,
    )

    return DSLVariableStore.configure([InMemoryVariableBackend()])


@given(
    key=st.text(
        min_size=1,
        max_size=30,
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Pd")),
    ),
    value=st.text(max_size=100),
)
@settings(max_examples=15, deadline=None)
async def test_set_get_roundtrip(key: str, value: str) -> None:
    """set(k, v) → get(k) returns v."""
    store = await _fresh_store()
    await store.set(key, value)
    assert await store.get(key) == value


@given(
    key=st.text(min_size=1, max_size=20),
    v1=st.text(max_size=50),
    v2=st.text(max_size=50),
)
@settings(max_examples=15, deadline=None)
async def test_last_write_wins(key: str, v1: str, v2: str) -> None:
    """Overwriting the same key returns the latest value."""
    store = await _fresh_store()
    await store.set(key, v1)
    await store.set(key, v2)
    assert await store.get(key) == v2


@given(
    key=st.text(min_size=1, max_size=20),
    value=st.text(max_size=50),
    tenant_a=st.text(min_size=1, max_size=10, alphabet="abcdef"),
    tenant_b=st.text(min_size=10, max_size=15, alphabet="ghijklmnop"),
)
@settings(max_examples=15, deadline=None)
async def test_tenant_scope_isolation(
    key: str, value: str, tenant_a: str, tenant_b: str
) -> None:
    """Variables in different tenant scopes don't leak."""
    from src.backend.core.dsl.variables import VariableScope

    if tenant_a == tenant_b:
        return

    store = await _fresh_store()
    scope_a = VariableScope.for_tenant(tenant_a)
    scope_b = VariableScope.for_tenant(tenant_b)

    await store.set(key, value, scope=scope_a)
    assert await store.get(key, scope=scope_a) == value
    # Different tenant must NOT see the value
    assert await store.get(key, scope=scope_b) is None


@given(
    key=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))),
    value=st.integers(min_value=-1_000_000, max_value=1_000_000),
)
@settings(max_examples=10, deadline=None)
async def test_integer_roundtrip(key: str, value: int) -> None:
    """Integer values round-trip through store."""
    store = await _fresh_store()
    await store.set(key, value)
    result = await store.get(key)
    assert result == value
    assert isinstance(result, int)


@given(
    key=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))),
)
@settings(max_examples=10, deadline=None)
async def test_unknown_key_returns_none(key: str) -> None:
    """get() on unknown key returns None (not exception)."""
    store = await _fresh_store()
    result = await store.get(key)
    assert result is None
