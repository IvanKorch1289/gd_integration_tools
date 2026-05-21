"""Тесты RuntimeFeatureFlagOverrides (Sprint 16 Wave 9, CP-15)."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.feature_flags.runtime_overrides import (
    RuntimeFeatureFlagOverrides,
    get_runtime_overrides,
    reset_runtime_overrides,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Каждый тест начинает с чистого singleton'а."""
    reset_runtime_overrides()


def test_get_returns_default_when_no_override() -> None:
    overrides = RuntimeFeatureFlagOverrides()
    assert overrides.get("flag_a", default=False) is False
    assert overrides.get("flag_a", default=42) == 42


def test_set_global_override_returns_change_record() -> None:
    overrides = RuntimeFeatureFlagOverrides()
    change = overrides.set("flag_a", True, actor="user:alice")
    assert change.flag == "flag_a"
    assert change.tenant_id is None
    assert change.old_value is None
    assert change.new_value is True
    assert change.actor == "user:alice"


def test_set_overwrites_previous_value_tracks_old() -> None:
    overrides = RuntimeFeatureFlagOverrides()
    overrides.set("flag_a", False)
    change = overrides.set("flag_a", True, actor="user:bob")
    assert change.old_value is False
    assert change.new_value is True


def test_get_returns_global_override() -> None:
    overrides = RuntimeFeatureFlagOverrides()
    overrides.set("flag_a", True)
    assert overrides.get("flag_a", default=False) is True


def test_per_tenant_override_overrides_global() -> None:
    overrides = RuntimeFeatureFlagOverrides()
    overrides.set("flag_a", False)  # global=False
    overrides.set("flag_a", True, tenant_id="tenant-1")  # per-tenant=True

    assert overrides.get("flag_a", default=None) is False
    assert overrides.get("flag_a", default=None, tenant_id="tenant-1") is True
    assert overrides.get("flag_a", default=None, tenant_id="tenant-2") is False


def test_clear_removes_override_returns_change() -> None:
    overrides = RuntimeFeatureFlagOverrides()
    overrides.set("flag_a", True)
    change = overrides.clear("flag_a")
    assert change is not None
    assert change.old_value is True
    assert change.new_value is None
    assert overrides.get("flag_a", default="default") == "default"


def test_clear_nonexistent_returns_none() -> None:
    overrides = RuntimeFeatureFlagOverrides()
    assert overrides.clear("never_set") is None


def test_clear_tenant_does_not_affect_global() -> None:
    overrides = RuntimeFeatureFlagOverrides()
    overrides.set("flag_a", True)
    overrides.set("flag_a", False, tenant_id="tenant-1")
    overrides.clear("flag_a", tenant_id="tenant-1")
    assert overrides.get("flag_a", default=None) is True
    assert overrides.get("flag_a", default=None, tenant_id="tenant-1") is True


def test_has_override_per_tenant_priority() -> None:
    overrides = RuntimeFeatureFlagOverrides()
    assert not overrides.has_override("flag_a")
    overrides.set("flag_a", True, tenant_id="tenant-1")
    assert overrides.has_override("flag_a", tenant_id="tenant-1") is True
    assert overrides.has_override("flag_a") is False


def test_list_overrides_snapshot() -> None:
    overrides = RuntimeFeatureFlagOverrides()
    overrides.set("flag_a", True)
    overrides.set("flag_b", "v1", tenant_id="t1")
    overrides.set("flag_a", False, tenant_id="t2")

    snapshot = overrides.list_overrides()
    assert snapshot["global"] == {"flag_a": True}
    assert snapshot["per_tenant"] == {
        "t1": {"flag_b": "v1"},
        "t2": {"flag_a": False},
    }


def test_singleton_returns_same_instance() -> None:
    a = get_runtime_overrides()
    b = get_runtime_overrides()
    assert a is b


def test_reset_clears_singleton_state() -> None:
    overrides = get_runtime_overrides()
    overrides.set("flag_x", True)
    assert overrides.list_overrides()["global"] == {"flag_x": True}
    reset_runtime_overrides()
    # После reset — новый singleton, без overrides.
    overrides2 = get_runtime_overrides()
    assert overrides2.list_overrides() == {"global": {}, "per_tenant": {}}


@pytest.mark.asyncio
async def test_inmemory_provider_uses_runtime_override() -> None:
    """InMemoryProvider.resolve_boolean_value подхватывает runtime override."""
    from src.backend.core.feature_flags.openfeature_provider import InMemoryProvider

    provider = InMemoryProvider()
    # До override — default.
    value_before = await provider.resolve_boolean_value(
        "some_test_flag_runtime", default=False
    )
    assert value_before is False

    get_runtime_overrides().set("some_test_flag_runtime", True)
    value_after = await provider.resolve_boolean_value(
        "some_test_flag_runtime", default=False
    )
    assert value_after is True


@pytest.mark.asyncio
async def test_inmemory_provider_tenant_override_isolated() -> None:
    """Per-tenant override влияет только на свой EvaluationContext."""
    from src.backend.core.feature_flags.openfeature_provider import (
        EvaluationContext,
        InMemoryProvider,
    )

    provider = InMemoryProvider()
    get_runtime_overrides().set(
        "tenant_isolated_flag", True, tenant_id="tenant-special"
    )

    val_default_tenant = await provider.resolve_boolean_value(
        "tenant_isolated_flag",
        default=False,
        evaluation_context=EvaluationContext(tenant_id="tenant-other"),
    )
    val_special_tenant = await provider.resolve_boolean_value(
        "tenant_isolated_flag",
        default=False,
        evaluation_context=EvaluationContext(tenant_id="tenant-special"),
    )

    assert val_default_tenant is False
    assert val_special_tenant is True
