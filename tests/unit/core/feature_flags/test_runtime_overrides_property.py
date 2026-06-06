# ruff: noqa: S101
"""Property-based tests for RuntimeFeatureFlagOverrides (Sprint 42 W1 C-3).

Covers invariants of the singleton state machine:
- Priority: per-tenant override > global override > default
- set→get consistency, set→set overwrite, set→clear→get=default
- Tenant isolation: setting tenant A does NOT affect tenant B
- list_overrides snapshot consistency
- has_override consistent with get() != default
- FeatureFlagChange.old_value reflects previous state

Note: hypothesis rejects function-scoped fixtures (HealthCheck.function_scoped_fixture).
We use inline `RuntimeFeatureFlagOverrides()` per test instead.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.backend.core.feature_flags.runtime_overrides import RuntimeFeatureFlagOverrides

# Strategies
st_flag = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    min_size=1,
    max_size=20,
)
st_tenant = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    min_size=1,
    max_size=20,
)
st_value = st.one_of(
    st.booleans(),
    st.integers(min_value=-1000, max_value=1000),
    st.text(max_size=20),
)

PROP = settings(
    max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
PROP20 = settings(
    max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture]
)


# ── set → get consistency ───────────────────────────────────────────


@given(flag=st_flag, value=st_value)
@PROP
def test_set_then_get_returns_value(flag: str, value: object) -> None:
    """After set(flag, value), get(flag, default) returns value."""
    store = RuntimeFeatureFlagOverrides()
    store.set(flag, value)
    assert store.get(flag, default="<DEFAULT>") == value


def test_get_returns_default_when_no_override() -> None:
    """If no override set, get returns the default argument."""
    store = RuntimeFeatureFlagOverrides()
    assert store.get("missing_flag", default="DEFAULT") == "DEFAULT"
    assert store.get("missing_flag", default=None) is None
    assert store.get("missing_flag", default=42) == 42


# ── set → set: new value wins, old_value tracked ───────────────────


@given(flag=st_flag, v1=st_value, v2=st_value)
@PROP
def test_set_overwrites_previous_value(flag: str, v1: object, v2: object) -> None:
    """set(flag, v2) after set(flag, v1) returns v2 on get."""
    store = RuntimeFeatureFlagOverrides()
    store.set(flag, v1)
    change = store.set(flag, v2)
    assert change.old_value == v1
    assert change.new_value == v2
    assert store.get(flag, default="<DEFAULT>") == v2


# ── set → clear → get = default ─────────────────────────────────────


@given(flag=st_flag, value=st_value)
@PROP
def test_clear_removes_override(flag: str, value: object) -> None:
    """clear(flag) after set(flag, value) restores default on get."""
    store = RuntimeFeatureFlagOverrides()
    store.set(flag, value)
    change = store.clear(flag)
    assert change is not None
    assert change.old_value == value
    assert change.new_value is None
    assert store.get(flag, default="<DEFAULT>") == "<DEFAULT>"


def test_clear_nonexistent_returns_none() -> None:
    """clear(flag) on unset flag returns None (no change event)."""
    store = RuntimeFeatureFlagOverrides()
    result = store.clear("never_set")
    assert result is None


# ── Priority: per-tenant > global > default ────────────────────────


@given(flag=st_flag, g_val=st_value, t_val=st_value, tenant=st_tenant)
@PROP
def test_per_tenant_overrides_global(
    flag: str, g_val: object, t_val: object, tenant: str
) -> None:
    """Per-tenant override takes precedence over global override."""
    store = RuntimeFeatureFlagOverrides()
    store.set(flag, g_val)  # global
    store.set(flag, t_val, tenant_id=tenant)  # per-tenant
    # Tenant lookup: per-tenant wins
    assert store.get(flag, default="<D>", tenant_id=tenant) == t_val
    # No-tenant lookup: global wins
    assert store.get(flag, default="<D>") == g_val


@given(flag=st_flag, g_val=st_value, t_val=st_value, tenant=st_tenant)
@PROP
def test_other_tenant_unaffected(
    flag: str, g_val: object, t_val: object, tenant: str
) -> None:
    """Setting tenant A does NOT affect tenant B (isolation)."""
    store = RuntimeFeatureFlagOverrides()
    other_tenant = tenant + "_other"  # guaranteed different
    store.set(flag, t_val, tenant_id=tenant)
    store.set(flag, g_val)  # global
    # Other tenant: falls back to global
    assert store.get(flag, default="<D>", tenant_id=other_tenant) == g_val


# ── has_override consistency ───────────────────────────────────────


@given(flag=st_flag, value=st_value)
@PROP
def test_has_override_after_set(flag: str, value: object) -> None:
    """has_override(flag) returns True after set."""
    store = RuntimeFeatureFlagOverrides()
    store.set(flag, value)
    assert store.has_override(flag) is True


def test_has_override_false_when_unset() -> None:
    """has_override(flag) returns False for unset flag."""
    store = RuntimeFeatureFlagOverrides()
    assert store.has_override("never_set") is False


@given(flag=st_flag, value=st_value, tenant=st_tenant)
@PROP
def test_has_override_tenant_scoped(
    flag: str, value: object, tenant: str
) -> None:
    """has_override(flag, tenant_id=A) doesn't leak to tenant_id=None."""
    store = RuntimeFeatureFlagOverrides()
    store.set(flag, value, tenant_id=tenant)
    assert store.has_override(flag, tenant_id=tenant) is True
    # Global scope (no tenant): no override
    assert store.has_override(flag) is False


# ── list_overrides snapshot ────────────────────────────────────────


@given(
    flags=st.lists(st_flag, min_size=1, max_size=5, unique=True),
    value=st_value,
    tenant=st_tenant,
)
@PROP20
def test_list_overrides_snapshot(
    flags: list[str], value: object, tenant: str
) -> None:
    """list_overrides returns deep copy: mutating snapshot doesn't affect store."""
    store = RuntimeFeatureFlagOverrides()
    for f in flags:
        store.set(f, value)
    store.set("t_flag", value, tenant_id=tenant)

    snap = store.list_overrides()
    # Mutate snapshot
    snap["global"]["new_key"] = "evil"
    snap["per_tenant"][tenant]["new_key"] = "evil"

    # Original store should be unaffected
    assert "new_key" not in store.list_overrides()["global"]
    assert "new_key" not in store.list_overrides()["per_tenant"].get(tenant, {})


# ── reset() clears everything ───────────────────────────────────────


@given(flag=st_flag, value=st_value, tenant=st_tenant)
@PROP20
def test_reset_clears_all_overrides(
    flag: str, value: object, tenant: str
) -> None:
    """reset() clears both global and per-tenant overrides."""
    store = RuntimeFeatureFlagOverrides()
    store.set(flag, value)
    store.set(flag, value, tenant_id=tenant)
    store.reset()
    snap = store.list_overrides()
    assert snap == {"global": {}, "per_tenant": {}}
    assert store.get(flag, default="<D>") == "<D>"
    assert store.get(flag, default="<D>", tenant_id=tenant) == "<D>"
