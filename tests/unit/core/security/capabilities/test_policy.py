"""ADR-0054 — тесты :class:`CapabilityPolicy`."""

from __future__ import annotations

import pytest

from src.backend.core.security.capabilities.policy import (
    CapabilityPolicy,
    CapabilityRule,
    PolicyDecision,
)


def test_no_rules_returns_no_match() -> None:
    """Пустая policy → no_match decision."""
    policy = CapabilityPolicy([])
    decision = policy.evaluate(
        tenant="t1", principal="p1", capability="net.outbound", scope=None
    )
    assert decision.effect == "no_match"
    assert decision.rule is None


def test_single_allow_rule_matches() -> None:
    """Single allow-правило → effect=allow + rule populated."""
    rule = CapabilityRule(
        effect="allow",
        capability="net.outbound",
        scope_glob="*",
        tenant="*",
        principal="*",
        priority=100,
    )
    policy = CapabilityPolicy([rule])
    decision = policy.evaluate(
        tenant="t1",
        principal="p1",
        capability="net.outbound",
        scope="net.outbound:host.internal:internal",
    )
    assert decision.effect == "allow"
    assert decision.rule is rule


def test_deny_beats_allow_same_priority() -> None:
    """При равных priority deny > allow (tie-break)."""
    allow_rule = CapabilityRule(
        effect="allow", capability="net.outbound", scope_glob="*", priority=100
    )
    deny_rule = CapabilityRule(
        effect="deny", capability="net.outbound", scope_glob="*", priority=100
    )
    policy = CapabilityPolicy([allow_rule, deny_rule])
    decision = policy.evaluate(
        tenant="t1", principal="p1", capability="net.outbound", scope="net.outbound:a:b"
    )
    assert decision.effect == "deny"
    assert decision.rule is deny_rule


def test_higher_priority_wins() -> None:
    """Higher priority пере wins lower priority независимо от effect."""
    high_allow = CapabilityRule(
        effect="allow", capability="net.outbound", scope_glob="*", priority=200
    )
    low_deny = CapabilityRule(
        effect="deny", capability="net.outbound", scope_glob="*", priority=50
    )
    policy = CapabilityPolicy([low_deny, high_allow])
    decision = policy.evaluate(
        tenant="t1", principal="p1", capability="net.outbound", scope="x:y:z"
    )
    assert decision.effect == "allow"


def test_tenant_filter_applies() -> None:
    """Правило с конкретным tenant не сматчится для другого tenant."""
    rule = CapabilityRule(
        effect="deny",
        capability="net.outbound",
        scope_glob="*",
        tenant="tenant_a",
        priority=100,
    )
    policy = CapabilityPolicy([rule])
    decision_a = policy.evaluate(
        tenant="tenant_a", principal="p1", capability="net.outbound", scope="x:y"
    )
    decision_b = policy.evaluate(
        tenant="tenant_b", principal="p1", capability="net.outbound", scope="x:y"
    )
    assert decision_a.effect == "deny"
    assert decision_b.effect == "no_match"


def test_principal_filter_applies() -> None:
    """Правило с конкретным principal не сматчится для другого principal."""
    rule = CapabilityRule(
        effect="allow",
        capability="db.read",
        scope_glob="*",
        principal="route_credit_check",
        priority=100,
    )
    policy = CapabilityPolicy([rule])
    decision_match = policy.evaluate(
        tenant="*", principal="route_credit_check", capability="db.read", scope="x:y"
    )
    decision_other = policy.evaluate(
        tenant="*", principal="route_other", capability="db.read", scope="x:y"
    )
    assert decision_match.effect == "allow"
    assert decision_other.effect == "no_match"


def test_scope_glob_matching() -> None:
    """Scope-glob с сегментами `:` корректно сматчится."""
    rule = CapabilityRule(
        effect="allow",
        capability="net.outbound",
        scope_glob="net.outbound:*.internal:internal",
        priority=100,
    )
    policy = CapabilityPolicy([rule])
    decision_match = policy.evaluate(
        tenant="t1",
        principal="p1",
        capability="net.outbound",
        scope="net.outbound:host.internal:internal",
    )
    decision_external = policy.evaluate(
        tenant="t1",
        principal="p1",
        capability="net.outbound",
        scope="net.outbound:host.external:external",
    )
    assert decision_match.effect == "allow"
    assert decision_external.effect == "no_match"


def test_capability_filter() -> None:
    """Правила для другой capability не сматчатся."""
    rule = CapabilityRule(
        effect="allow", capability="net.outbound", scope_glob="*", priority=100
    )
    policy = CapabilityPolicy([rule])
    decision = policy.evaluate(
        tenant="t1", principal="p1", capability="db.read", scope="any"
    )
    assert decision.effect == "no_match"


def test_policy_decision_is_dataclass() -> None:
    """:class:`PolicyDecision` — frozen dataclass с slots."""
    decision = PolicyDecision(effect="allow", rule=None)
    assert decision.effect == "allow"
    with pytest.raises(AttributeError):
        decision.effect = "deny"  # type: ignore[misc]


def test_rules_property_exposes_sorted_order() -> None:
    """``rules`` свойство возвращает правила в evaluation order."""
    r_low = CapabilityRule(effect="allow", capability="x.y", priority=10)
    r_high = CapabilityRule(effect="deny", capability="x.y", priority=100)
    policy = CapabilityPolicy([r_low, r_high])
    assert policy.rules == (r_high, r_low)
