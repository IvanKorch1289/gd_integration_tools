"""S44 W6: unit tests for services/admin/audit.py.

Covers emission + audit-callback state management. Per-agent-41
analytics recommendation: bounded test for smallest 0%-covered
service file. Coverage target: services/admin/audit.py +
emission behavior.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.services.admin import audit


class TestAdminAuditCallback:
    """Audit callback registration + reset (state-based tests)."""

    def test_set_audit_callback_stores_function(self) -> None:
        """set_audit_callback stores callback in module state."""

        def cb(event: dict[str, Any]) -> None:
            pass

        audit.set_audit_callback(cb)
        assert audit._audit_callback is cb  # type: ignore[attr-defined]

    def test_set_audit_callback_none_clears(self) -> None:
        """set_audit_callback(None) clears stored callback."""

        def cb(event: dict[str, Any]) -> None:
            pass

        audit.set_audit_callback(cb)
        audit.set_audit_callback(None)
        assert audit._audit_callback is None  # type: ignore[attr-defined]


class TestEmitAdminAction:
    """emit_admin_action() event shape + dispatch."""

    def test_emit_invokes_callback_with_event(self) -> None:
        """emit_admin_action calls _audit_callback with structured event."""
        captured: list[dict[str, Any]] = []

        def cb(event: dict[str, Any]) -> None:
            captured.append(event)

        audit.set_audit_callback(cb)
        try:
            audit.emit_admin_action(
                actor="alice",
                action="feature_flag.toggle",
                resource="flags/new_login",
                outcome="allowed",
                details={"new_value": True},
            )
        finally:
            audit.set_audit_callback(None)

        assert len(captured) == 1
        event = captured[0]
        assert event["event"] == "admin.action"
        assert event["actor"] == "alice"
        assert event["action"] == "feature_flag.toggle"
        assert event["resource"] == "flags/new_login"
        assert event["outcome"] == "allowed"
        assert event["details"] == {"new_value": True}
        assert "correlation_id" in event
        assert "timestamp" in event

    def test_emit_generates_correlation_id_when_missing(self) -> None:
        """emit_admin_action without correlation_id generates UUID4."""
        captured: list[dict[str, Any]] = []

        def cb(event: dict[str, Any]) -> None:
            captured.append(event)

        audit.set_audit_callback(cb)
        try:
            audit.emit_admin_action(
                actor="bob", action="session.list",
                resource="sessions", outcome="denied",
            )
        finally:
            audit.set_audit_callback(None)

        cid = captured[0]["correlation_id"]
        # UUID4 hex format: 36 chars with 4 hyphens
        assert len(cid) == 36
        assert cid.count("-") == 4

    def test_emit_uses_provided_correlation_id(self) -> None:
        """emit_admin_action with correlation_id uses provided value."""
        captured: list[dict[str, Any]] = []

        def cb(event: dict[str, Any]) -> None:
            captured.append(event)

        audit.set_audit_callback(cb)
        try:
            audit.emit_admin_action(
                actor="carol", action="x", resource="y",
                outcome="allowed", correlation_id="abc-123",
            )
        finally:
            audit.set_audit_callback(None)

        assert captured[0]["correlation_id"] == "abc-123"

    def test_emit_no_callback_logs_only(self) -> None:
        """emit_admin_action without callback logs debug, doesn't raise."""
        audit.set_audit_callback(None)
        # Should not raise — only logger.debug emission
        audit.emit_admin_action(
            actor="system", action="startup", resource="app",
            outcome="allowed",
        )

    def test_emit_callback_exception_swallowed(self) -> None:
        """Callback exception is logged but doesn't propagate."""

        def bad_cb(event: dict[str, Any]) -> None:
            raise ValueError("intentional test failure")

        audit.set_audit_callback(bad_cb)
        # Must not raise — emit_admin_action catches Exception internally
        audit.emit_admin_action(
            actor="x", action="y", resource="z", outcome="allowed",
        )
        audit.set_audit_callback(None)


@pytest.fixture(autouse=True)
def _cleanup_callback() -> None:
    """Ensure audit callback is reset after each test."""
    yield
    audit.set_audit_callback(None)
