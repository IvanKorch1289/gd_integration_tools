"""Unit tests for tenant-aware :class:`CapabilityGate` (Sprint 36 V15 GAP).

Покрывает:
* check_tenant: granted/denied, scope mismatch, default tenant, policy interaction.
* declare_tenant / revoke_tenant / list_allocated_tenant — per-tenant storage.
* Per-tenant LRU cache (granted cached, denied cached after first miss).
* Audit events ``capability.allocated`` / ``capability.revoked``.
* Backward compat: ``check()`` (без tenant) работает как раньше.

NB: ``db.*`` capabilities используют :class:`ExactAliasMatcher` (DSN-стиль),
поэтому scope для них — строки-алиасы без glob-символов. ``net.*`` /
``mq.*`` / ``workflow.*`` — :class:`GlobScopeMatcher` с sep='``.''``;
``cache.*`` — :class:`SegmentedGlobMatcher` с sep='``:'; ``secrets.*`` —
:class:`URISchemeMatcher` (``vault://`` / ``env://`` / ``kms://``).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.security.capabilities.errors import CapabilityDeniedError
from src.backend.core.security.capabilities.gate import CapabilityGate
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.core.security.capabilities.tenant import (
    SYSTEM_TENANT_ID,
    CapabilityTenant,
    TenantContext,
)

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def audit_events() -> list[dict[str, Any]]:
    """Список для записи audit events от gate."""
    return []


@pytest.fixture
def gate(audit_events: list[dict[str, Any]]) -> CapabilityGate:
    """CapabilityGate с audit callback, пишущим в :data:`audit_events`."""

    def safe(event: dict[str, object]) -> None:
        try:
            audit_events.append(dict(event))
        except Exception:  # noqa: BLE001, S110
            pass

    return CapabilityGate(audit=safe)


# ── CapabilityTenant + TenantContext dataclasses ──────────────────


@pytest.mark.unit
def test_capability_tenant_is_system() -> None:
    """``id='_system'`` → ``is_system`` True."""
    t = CapabilityTenant(id=SYSTEM_TENANT_ID, principal="core")
    assert t.is_system is True


@pytest.mark.unit
def test_capability_tenant_is_not_system() -> None:
    """Любой другой id → ``is_system`` False."""
    t = CapabilityTenant(id="tenant_a", principal="plugin_credit")
    assert t.is_system is False


@pytest.mark.unit
def test_capability_tenant_str_with_scope() -> None:
    """``__str__`` включает scope_glob если задан."""
    t = CapabilityTenant(id="t1", principal="p1", scope_glob="db:*")
    assert "db:*" in str(t)
    assert "t1" in str(t)


@pytest.mark.unit
def test_tenant_context_to_tenant() -> None:
    """``to_tenant()`` материализует CapabilityTenant (scope_glob=None)."""
    ctx = TenantContext(tenant_id="t1", principal_id="plugin_a")
    t = ctx.to_tenant()
    assert t.id == "t1"
    assert t.principal == "plugin_a"
    assert t.scope_glob is None


# ── check_tenant: basic semantics ──────────────────────────────────


@pytest.mark.unit
def test_check_tenant_granted_after_declare(gate: CapabilityGate) -> None:
    """После ``declare_tenant`` → ``check_tenant`` возвращает True.

    ``db.read`` использует :class:`ExactAliasMatcher` — scope должно
    быть точным alias-именем (DSN), без glob.
    """
    gate.declare_tenant(
        CapabilityRef(name="db.read", scope="credit_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    assert gate.check_tenant("db.read", "tenant_a", "plugin_x", "credit_db") is True


@pytest.mark.unit
def test_check_tenant_granted_cache_resource(gate: CapabilityGate) -> None:
    """``cache.read`` использует SegmentedGlobMatcher(sep=':'), glob работает."""
    gate.declare_tenant(
        CapabilityRef(name="cache.read", scope="cache:tenant_a:*"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    # Glob 'cache:tenant_a:*' matches single segment 'users'.
    assert (
        gate.check_tenant("cache.read", "tenant_a", "plugin_x", "cache:tenant_a:users")
        is True
    )


@pytest.mark.unit
def test_check_tenant_denied_no_declaration(gate: CapabilityGate) -> None:
    """Без ``declare_tenant`` → ``check_tenant`` возвращает False (не raise)."""
    assert gate.check_tenant("db.read", "tenant_a", "plugin_x", "any_alias") is False


@pytest.mark.unit
def test_check_tenant_mismatch_tenant(gate: CapabilityGate) -> None:
    """Декларация для tenant_a, check для tenant_b → denied."""
    gate.declare_tenant(
        CapabilityRef(name="db.read", scope="credit_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    assert gate.check_tenant("db.read", "tenant_b", "plugin_x", "credit_db") is False


@pytest.mark.unit
def test_check_tenant_scope_mismatch(gate: CapabilityGate) -> None:
    """Scope, не равный declared (для exact matcher) → denied."""
    gate.declare_tenant(
        CapabilityRef(name="db.read", scope="credit_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    # Запрошен другой alias → denied.
    assert gate.check_tenant("db.read", "tenant_a", "plugin_x", "audit_db") is False


@pytest.mark.unit
def test_check_tenant_default_system(audit_events: list[dict[str, Any]]) -> None:
    """``check()`` без tenant использует SYSTEM_TENANT_ID, не падает."""
    g = CapabilityGate(audit=lambda e: audit_events.append(dict(e)))
    g.declare("plugin_x", [CapabilityRef(name="db.read", scope="credit_db")])
    # Не должно raise — backward compat с existing test suite.
    g.check("plugin_x", "db.read", "credit_db")


@pytest.mark.unit
def test_check_tenant_unknown_capability_returns_false(gate: CapabilityGate) -> None:
    """``check_tenant`` для незадекларированной capability → ``False`` (НЕ raise).

    NB: ``check_tenant`` возвращает ``bool`` (без raise), в отличие от
    :meth:`CapabilityGate.check`, который raise'ит ``CapabilityDeniedError``.
    Для unknown capability (даже с валидной грамматикой ``<resource>.<verb>``)
    результат — ``False`` без side effects.
    """
    # Грамматика корректна, но такой capability нет в _tenant_declarations.
    assert gate.check_tenant("nonexistent.verb", "tenant_a", "plugin_x") is False


@pytest.mark.unit
def test_check_unknown_capability_raises() -> None:
    """Legacy ``check()`` (не tenant-aware) raise'ит ``CapabilityDeniedError``.

    NB: :meth:`CapabilityGate.check` (не ``check_tenant``) при отсутствии
    declaration raise'ит ``CapabilityDeniedError`` (НЕ ``CapabilityNotFoundError``).
    ``validate_ref`` вызывается только в ``declare()``, не в ``check()``.
    """
    g = CapabilityGate()
    with pytest.raises(CapabilityDeniedError):
        g.check("plugin_x", "nonexistent.verb", "any_scope")


# ── Per-tenant LRU cache ──────────────────────────────────────────


@pytest.mark.unit
def test_check_tenant_lru_cache_granted(
    gate: CapabilityGate, audit_events: list[dict[str, Any]]
) -> None:
    """Granted результат кэшируется: повторный check не падает."""
    gate.declare_tenant(
        CapabilityRef(name="db.read", scope="credit_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    # Первый check.
    assert gate.check_tenant("db.read", "tenant_a", "plugin_x", "credit_db") is True
    # Второй check (cache hit) — должен вернуть True.
    assert gate.check_tenant("db.read", "tenant_a", "plugin_x", "credit_db") is True
    # Audit events были эмитированы для обоих вызовов.
    granted_events = [e for e in audit_events if e.get("outcome") == "granted"]
    assert len(granted_events) >= 2


@pytest.mark.unit
def test_revoke_tenant_invalidates_cache(gate: CapabilityGate) -> None:
    """``revoke_tenant`` инвалидирует per-tenant cache."""
    gate.declare_tenant(
        CapabilityRef(name="db.read", scope="credit_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    assert gate.check_tenant("db.read", "tenant_a", "plugin_x", "credit_db") is True
    gate.revoke_tenant("db.read", "tenant_a")
    assert gate.check_tenant("db.read", "tenant_a", "plugin_x", "credit_db") is False


@pytest.mark.unit
def test_revoke_tenant_does_not_affect_other_tenants(gate: CapabilityGate) -> None:
    """``revoke_tenant`` для tenant_a не трогает tenant_b."""
    gate.declare_tenant(
        CapabilityRef(name="db.read", scope="credit_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    gate.declare_tenant(
        CapabilityRef(name="db.read", scope="audit_db"),
        tenant="tenant_b",
        principal="plugin_x",
    )
    gate.revoke_tenant("db.read", "tenant_a")
    assert gate.check_tenant("db.read", "tenant_a", "plugin_x", "credit_db") is False
    assert gate.check_tenant("db.read", "tenant_b", "plugin_x", "audit_db") is True


# ── declare_tenant / list_allocated_tenant ─────────────────────────


@pytest.mark.unit
def test_declare_tenant_duplicate_raises(gate: CapabilityGate) -> None:
    """Двойной ``declare_tenant`` для (tenant, principal, capability) → ValueError."""
    gate.declare_tenant(
        CapabilityRef(name="db.read", scope="any_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    with pytest.raises(ValueError, match="already declared"):
        gate.declare_tenant(
            CapabilityRef(name="db.read", scope="any_db"),
            tenant="tenant_a",
            principal="plugin_x",
        )


@pytest.mark.unit
def test_list_allocated_tenant_empty(gate: CapabilityGate) -> None:
    """Пустой tenant → пустой tuple."""
    assert gate.list_allocated_tenant("nonexistent") == ()


@pytest.mark.unit
def test_list_allocated_tenant_with_declarations(gate: CapabilityGate) -> None:
    """``list_allocated_tenant`` возвращает все декларации (через principal'ов)."""
    gate.declare_tenant(
        CapabilityRef(name="db.read", scope="any_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    gate.declare_tenant(
        CapabilityRef(name="db.write", scope="any_db"),
        tenant="tenant_a",
        principal="plugin_y",
    )
    refs = gate.list_allocated_tenant("tenant_a")
    names = {r.name for r in refs}
    assert names == {"db.read", "db.write"}


# ── Audit events ──────────────────────────────────────────────────


@pytest.mark.unit
def test_declare_tenant_emits_audit(audit_events: list[dict[str, Any]]) -> None:
    """``declare_tenant`` эмитит ``capability.allocated`` event."""
    g = CapabilityGate(audit=lambda e: audit_events.append(dict(e)))
    g.declare_tenant(
        CapabilityRef(name="db.read", scope="any_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    allocated = [e for e in audit_events if e.get("event") == "capability.allocated"]
    assert len(allocated) == 1
    assert allocated[0].get("tenant") == "tenant_a"
    assert allocated[0].get("capability") == "db.read"


@pytest.mark.unit
def test_revoke_tenant_emits_audit(audit_events: list[dict[str, Any]]) -> None:
    """``revoke_tenant`` эмитит ``capability.revoked`` event (если было что revoke)."""
    g = CapabilityGate(audit=lambda e: audit_events.append(dict(e)))
    g.declare_tenant(
        CapabilityRef(name="db.read", scope="any_db"),
        tenant="tenant_a",
        principal="plugin_x",
    )
    audit_events.clear()  # Сброс declare events.
    g.revoke_tenant("db.read", "tenant_a")
    revoked = [e for e in audit_events if e.get("event") == "capability.revoked"]
    assert len(revoked) == 1
    assert revoked[0].get("tenant") == "tenant_a"


@pytest.mark.unit
def test_revoke_tenant_no_audit_when_not_declared(
    audit_events: list[dict[str, Any]],
) -> None:
    """``revoke_tenant`` для незадекларированной capability → НЕ эмитит audit."""
    g = CapabilityGate(audit=lambda e: audit_events.append(dict(e)))
    g.revoke_tenant("db.read", "tenant_a")
    assert not any(e.get("event") == "capability.revoked" for e in audit_events)


# ── Backward compat ───────────────────────────────────────────────


@pytest.mark.unit
def test_check_backward_compat_grants() -> None:
    """``check()`` (не tenant-aware) без policy — granted с правильным scope."""
    g = CapabilityGate()
    g.declare("plugin_x", [CapabilityRef(name="db.read", scope="credit_db")])
    # Granted — не raise.
    g.check("plugin_x", "db.read", "credit_db")


@pytest.mark.unit
def test_check_backward_compat_denies_no_declaration() -> None:
    """``check()`` без declaration → ``CapabilityDeniedError``."""
    g = CapabilityGate()
    with pytest.raises(CapabilityDeniedError):
        g.check("plugin_x", "db.read", "credit_db")
