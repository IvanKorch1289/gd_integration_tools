# ruff: noqa: S101
"""Sprint 14 K1 W4 — unit-тесты ``CapabilityAuditEvent``."""

from __future__ import annotations

from src.backend.core.security.capabilities import (
    CapabilityAuditEvent,
    log_capability_event,
)


def test_grant_event_kind() -> None:
    event = CapabilityAuditEvent(
        plugin="alpha",
        capability="db.read",
        scope="orders",
        granted=True,
        tenant="t-1",
        actor="user@bank.local",
    )
    assert event.kind == "capability_grant"
    assert event.granted is True
    assert event.denial_reason is None


def test_deny_event_kind() -> None:
    event = CapabilityAuditEvent(
        plugin="alpha",
        capability="db.write",
        scope="orders",
        granted=False,
        denial_reason="policy_rule:no_write_for_alpha",
        tenant="t-1",
        actor="user@bank.local",
    )
    assert event.kind == "capability_deny"
    assert event.denial_reason == "policy_rule:no_write_for_alpha"


def test_to_dict_serialises_all_fields() -> None:
    event = CapabilityAuditEvent(
        plugin="alpha",
        capability="net.outbound",
        scope="api.skb.ru",
        granted=True,
        correlation_id="abc-123",
        extra={"route_id": "credit.check"},
    )
    payload = event.to_dict()
    assert payload["kind"] == "capability_grant"
    assert payload["plugin"] == "alpha"
    assert payload["capability"] == "net.outbound"
    assert payload["scope"] == "api.skb.ru"
    assert payload["correlation_id"] == "abc-123"
    assert payload["extra"] == {"route_id": "credit.check"}


def test_defaults_for_tenant_and_actor() -> None:
    event = CapabilityAuditEvent(
        plugin="alpha", capability="db.read", scope=None, granted=True
    )
    assert event.tenant == "_system"
    assert event.actor == "_anonymous"
    assert event.timestamp.startswith("20")  # ISO-8601


def test_log_capability_event_does_not_raise() -> None:
    event = CapabilityAuditEvent(
        plugin="alpha", capability="db.read", scope=None, granted=True
    )
    # smoke-test: log call should be safe
    log_capability_event(event)


def test_frozen_dataclass_rejects_mutation() -> None:
    event = CapabilityAuditEvent(
        plugin="alpha", capability="db.read", scope=None, granted=True
    )
    import dataclasses

    try:
        event.plugin = "other"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("expected FrozenInstanceError")
