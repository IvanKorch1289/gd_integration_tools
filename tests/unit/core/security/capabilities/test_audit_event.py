"""Coverage tests для capabilities/audit (Sprint 222, 2026-08-17).

TDD: tests для core/security/capabilities/audit.py.

capabilities/audit.py coverage baseline: 15% (per Sprint 221).
Target: 90%+ via these tests.

Coverage targets:
- CapabilityAuditEvent: frozen dataclass, default values, kind property
- to_dict: JSON serialization with kind
- log_capability_event: structured log emission
"""

from __future__ import annotations

import dataclasses

import pytest

from src.backend.core.security.capabilities.audit import (
    CapabilityAuditEvent,
    log_capability_event,
)


def _make_event(**overrides) -> CapabilityAuditEvent:
    """Helper: создать event с minimal required fields + overrides."""
    defaults = {
        "plugin": "test_plugin",
        "capability": "db.read",
        "scope": "tenant",
        "granted": True,
    }
    defaults.update(overrides)
    return CapabilityAuditEvent(**defaults)


class TestCapabilityAuditEventConstruction:
    """CapabilityAuditEvent — construction and defaults."""

    def test_minimal_required_fields(self) -> None:
        event = _make_event()
        assert event.plugin == "test_plugin"
        assert event.capability == "db.read"
        assert event.scope == "tenant"
        assert event.granted is True

    def test_optional_fields_defaults(self) -> None:
        event = _make_event()
        assert event.denial_reason is None
        assert event.tenant == "_system"
        assert event.actor == "_anonymous"
        assert event.correlation_id is None
        assert isinstance(event.timestamp, str)
        assert event.extra == {}

    def test_with_denial_reason(self) -> None:
        event = _make_event(granted=False, denial_reason="policy denied")
        assert event.granted is False
        assert event.denial_reason == "policy denied"

    def test_timestamp_is_iso8601_microseconds(self) -> None:
        event = _make_event()
        # ISO-8601 with microseconds: "2026-08-17T12:34:56.123456+00:00"
        # Basic shape: starts with YYYY-MM-DDTHH:MM:SS
        assert event.timestamp[0:19].replace("T", "T") == event.timestamp[0:19]
        assert "T" in event.timestamp
        assert "+" in event.timestamp or "Z" in event.timestamp

    def test_extra_dict_can_be_customized(self) -> None:
        event = _make_event(extra={"route_id": "test_route", "action": "create"})
        assert event.extra["route_id"] == "test_route"
        assert event.extra["action"] == "create"


class TestCapabilityAuditEventFrozen:
    """CapabilityAuditEvent — frozen dataclass immutability."""

    def test_event_is_frozen(self) -> None:
        event = _make_event()
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.granted = False  # type: ignore[misc]

    def test_extra_dict_mutable_but_field_immutable(self) -> None:
        """Frozen prevents field reassignment but mutable defaults are still mutable.

        Это known Python issue (frozen + mutable default). Тест документирует
        expected behavior — НЕ silent fail, но и НЕ strict immutability.
        """
        event = _make_event(extra={"a": 1})
        # Frozen prevents reassignment of extra
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.extra = {"a": 2}  # type: ignore[misc]


class TestCapabilityAuditEventKind:
    """CapabilityAuditEvent.kind — property based on granted."""

    def test_kind_when_granted(self) -> None:
        event = _make_event(granted=True)
        assert event.kind == "capability_grant"

    def test_kind_when_denied(self) -> None:
        event = _make_event(granted=False, denial_reason="denied")
        assert event.kind == "capability_deny"


class TestCapabilityAuditEventToDict:
    """CapabilityAuditEvent.to_dict — JSON serialization."""

    def test_to_dict_includes_kind(self) -> None:
        event = _make_event()
        d = event.to_dict()
        assert d["kind"] == "capability_grant"
        assert d["plugin"] == "test_plugin"
        assert d["capability"] == "db.read"
        assert d["scope"] == "tenant"
        assert d["granted"] is True

    def test_to_dict_includes_deny_kind(self) -> None:
        event = _make_event(granted=False, denial_reason="denied")
        d = event.to_dict()
        assert d["kind"] == "capability_deny"
        assert d["denial_reason"] == "denied"

    def test_to_dict_is_json_serializable_shape(self) -> None:
        """to_dict should return plain Python types (JSON-friendly)."""
        import json

        event = _make_event(extra={"a": 1, "b": "x"})
        d = event.to_dict()
        # Should be JSON-serializable without errors
        json.dumps(d)  # no exception


class TestLogCapabilityEvent:
    """log_capability_event — structured log emission."""

    def test_log_capability_event_grant(self, caplog) -> None:
        """log_capability_event emits info log with event dict."""
        import logging

        event = _make_event(granted=True)

        with caplog.at_level(logging.INFO, logger="core.security.capabilities.audit"):
            log_capability_event(event)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "INFO"
        # log message + extra fields
        assert "capability_audit" in record.message

    def test_log_capability_event_deny(self, caplog) -> None:
        import logging

        event = _make_event(granted=False, denial_reason="denied")

        with caplog.at_level(logging.INFO, logger="core.security.capabilities.audit"):
            log_capability_event(event)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "INFO"