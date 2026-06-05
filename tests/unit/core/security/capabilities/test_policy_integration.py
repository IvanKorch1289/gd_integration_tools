"""Unit tests for ``CapabilityPolicy`` integration в :class:`CapabilityGate`.

Покрывает:
* Policy ``allow`` → granted без declaration check.
* Policy ``deny`` → denied до declaration check.
* Policy ``no_match`` → fallback на declaration check.
* Priority tie-break (deny > allow при равном priority).
* Tenant-specific deny (rule для tenant_a, allow для остальных).
* No policy → backward compat (declaration-only check).
"""

from __future__ import annotations

import pytest

from src.backend.core.security.capabilities.gate import CapabilityGate
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.core.security.capabilities.policy import (
    CapabilityPolicy,
    CapabilityRule,
)

# ── Policy allow (skip declaration) ───────────────────────────────


@pytest.mark.unit
def test_policy_allow_skips_declaration_check() -> None:
    """Policy allow → granted даже БЕЗ declaration."""
    policy = CapabilityPolicy(
        [
            CapabilityRule(
                effect="allow",
                capability="net.outbound",
                tenant="*",
                principal="*",
                priority=10,
            )
        ]
    )
    g = CapabilityGate(policy=policy)
    # Нет declare — но policy allow → check_tenant = True.
    assert (
        g.check_tenant(
            "net.outbound", "tenant_a", "plugin_x", "net.outbound:example:80"
        )
        is True
    )


@pytest.mark.unit
def test_policy_allow_does_not_require_scope_match() -> None:
    """Policy allow без scope_glob пропускает ЛЮБОЙ scope."""
    policy = CapabilityPolicy(
        [
            CapabilityRule(
                effect="allow", capability="net.outbound", tenant="*", principal="*"
            )
        ]
    )
    g = CapabilityGate(policy=policy)
    # Любой scope — granted.
    assert g.check_tenant("net.outbound", "t1", "p1", "any:scope:here") is True
    assert g.check_tenant("net.outbound", "t1", "p1") is True


# ── Policy deny (block before declaration) ────────────────────────


@pytest.mark.unit
def test_policy_deny_blocks_even_with_declaration() -> None:
    """Policy deny → denied ДАЖЕ если declaration есть."""
    policy = CapabilityPolicy(
        [
            CapabilityRule(
                effect="deny",
                capability="secrets.read",
                tenant="tenant_a",
                principal="*",
                priority=100,
            )
        ]
    )
    g = CapabilityGate(policy=policy)
    # ``secrets.read`` использует URISchemeMatcher — vault:// для теста.
    g.declare_tenant(
        CapabilityRef(name="secrets.read", scope="vault://kv/*"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    # Declaration есть, но policy deny → denied.
    assert (
        g.check_tenant("secrets.read", "tenant_a", "plugin_x", "vault://kv/any")
        is False
    )


@pytest.mark.unit
def test_policy_deny_blocks_other_tenants_unaffected() -> None:
    """Policy deny для tenant_a не влияет на tenant_b."""
    policy = CapabilityPolicy(
        [
            CapabilityRule(
                effect="deny",
                capability="secrets.read",
                tenant="tenant_a",
                principal="*",
                priority=100,
            )
        ]
    )
    g = CapabilityGate(policy=policy)
    g.declare_tenant(
        CapabilityRef(name="secrets.read", scope="vault://kv/*"),
        tenant="tenant_b",
        principal="plugin_x",
    )
    # tenant_b — granted.
    assert (
        g.check_tenant("secrets.read", "tenant_b", "plugin_x", "vault://kv/any") is True
    )
    # tenant_a — denied.
    assert (
        g.check_tenant("secrets.read", "tenant_a", "plugin_x", "vault://kv/any")
        is False
    )


# ── Policy no_match (fallback) ────────────────────────────────────


@pytest.mark.unit
def test_policy_no_match_falls_back_to_declaration_granted() -> None:
    """Policy no_match → declaration check, declaration grant → granted."""
    policy = CapabilityPolicy(
        [
            # Правило для ДРУГОЙ capability → не match'ит нашу.
            CapabilityRule(
                effect="allow", capability="net.outbound", tenant="*", principal="*"
            )
        ]
    )
    g = CapabilityGate(policy=policy)
    # ``db.read`` exact matcher → exact scope.
    g.declare_tenant(
        CapabilityRef(name="db.read", scope="credit_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    # Policy no_match (rule для net.outbound не матчит db.read).
    # Fallback на declaration → granted.
    assert g.check_tenant("db.read", "tenant_a", "plugin_x", "credit_db") is True


@pytest.mark.unit
def test_policy_no_match_falls_back_to_declaration_denied() -> None:
    """Policy no_match → declaration check, NO declaration → denied."""
    policy = CapabilityPolicy(
        [
            CapabilityRule(
                effect="allow", capability="net.outbound", tenant="*", principal="*"
            )
        ]
    )
    g = CapabilityGate(policy=policy)
    # Нет declaration.
    assert g.check_tenant("db.read", "tenant_a", "plugin_x", "credit_db") is False


# ── Priority tie-break (deny > allow при равном priority) ─────────


@pytest.mark.unit
def test_priority_deny_beats_allow_at_equal_priority() -> None:
    """Два правила с одинаковым priority: deny > allow."""
    policy = CapabilityPolicy(
        [
            CapabilityRule(
                effect="allow",
                capability="db.read",
                tenant="*",
                principal="*",
                priority=10,
            ),
            CapabilityRule(
                effect="deny",
                capability="db.read",
                tenant="*",
                principal="*",
                priority=10,
            ),
        ]
    )
    g = CapabilityGate(policy=policy)
    g.declare_tenant(
        CapabilityRef(name="db.read", scope="credit_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    # Deny правило с тем же priority побеждает.
    assert g.check_tenant("db.read", "tenant_a", "plugin_x", "credit_db") is False


@pytest.mark.unit
def test_priority_higher_wins_over_lower() -> None:
    """Правило с higher priority побеждает независимо от effect."""
    policy = CapabilityPolicy(
        [
            # lower priority — allow.
            CapabilityRule(
                effect="allow",
                capability="db.read",
                tenant="*",
                principal="*",
                priority=1,
            ),
            # higher priority — deny для конкретного tenant.
            CapabilityRule(
                effect="deny",
                capability="db.read",
                tenant="tenant_a",
                principal="*",
                priority=100,
            ),
        ]
    )
    g = CapabilityGate(policy=policy)
    g.declare_tenant(
        CapabilityRef(name="db.read", scope="credit_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    # Higher priority deny → побеждает для tenant_a.
    assert g.check_tenant("db.read", "tenant_a", "plugin_x", "credit_db") is False


# ── Tenant-specific policy ────────────────────────────────────────


@pytest.mark.unit
def test_tenant_specific_deny() -> None:
    """Deny rule для tenant_a, allow для остальных."""
    policy = CapabilityPolicy(
        [
            CapabilityRule(
                effect="allow",
                capability="net.outbound",
                tenant="*",
                principal="*",
                priority=1,
            ),
            CapabilityRule(
                effect="deny",
                capability="net.outbound",
                tenant="tenant_a",
                principal="*",
                priority=10,
            ),
        ]
    )
    g = CapabilityGate(policy=policy)
    # tenant_b — allow.
    assert g.check_tenant("net.outbound", "tenant_b", "plugin_x", "net:any") is True
    # tenant_a — deny.
    assert g.check_tenant("net.outbound", "tenant_a", "plugin_x", "net:any") is False


# ── No policy → backward compat ───────────────────────────────────


@pytest.mark.unit
def test_no_policy_uses_declaration_only() -> None:
    """Без policy → только declaration-based check."""
    g = CapabilityGate()  # policy=None по умолчанию
    g.declare_tenant(
        CapabilityRef(name="db.read", scope="credit_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    assert g.check_tenant("db.read", "tenant_a", "plugin_x", "credit_db") is True
    # Denied для другого scope.
    assert g.check_tenant("db.read", "tenant_a", "plugin_x", "audit_db") is False


@pytest.mark.unit
def test_no_policy_grants_for_legacy_check() -> None:
    """Backward compat: ``check()`` (не tenant) без policy работает как раньше."""
    g = CapabilityGate()
    g.declare("plugin_x", [CapabilityRef(name="db.read", scope="credit_db")])
    g.check("plugin_x", "db.read", "credit_db")  # Не должно raise.
