"""Tests for S106 W2 Audit facade per-domain helpers (Path A).

Subagent S105 W2 обнаружил 7 distinct patterns в legacy `_emit_audit`
callsites. Path A = additive helpers в ``core/audit/facade.py`` для
постепенной миграции. Эти тесты фиксируют контракты helpers.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.backend.core.audit import facade


@pytest.fixture
def mock_audit_service() -> Any:
    """Mock ``get_unified_audit_service().emit()`` return value."""
    mock_emit = patch(
        "src.backend.core.audit.facade._base.get_unified_audit_service"
    )
    with mock_emit as mock_get:
        svc = mock_get.return_value
        yield svc


class TestEmitAuthorizationDecision:
    """Pattern A: AuthorizationDecision → canonical kwargs."""

    def test_allowed_decision(self, mock_audit_service: Any) -> None:
        """allowed=True → outcome=success."""
        decision = type("D", (), {
            "allowed": True,
            "reason": "policy_match",
            "matched_policy": "p1",
            "scope_checked": "read",
            "evaluated_at": "2026-06-13T12:00:00Z",
        })()
        facade.emit_authorization_decision(
            decision=decision,
            principal="user:alice",
            resource="api:orders",
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["event"] == "authorization.decision"
        assert call.kwargs["actor"] == "user:alice"
        assert call.kwargs["resource"] == "api:orders"
        assert call.kwargs["outcome"] == "success"
        assert call.kwargs["details"]["allowed"] is True
        assert call.kwargs["details"]["reason"] == "policy_match"

    def test_denied_decision(self, mock_audit_service: Any) -> None:
        """allowed=False → outcome=denied."""
        decision = type("D", (), {
            "allowed": False, "reason": "scope_mismatch",
            "matched_policy": None, "scope_checked": "write",
            "evaluated_at": "2026-06-13T12:00:00Z",
        })()
        facade.emit_authorization_decision(
            decision=decision,
            principal="user:bob",
            resource="api:admin",
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["outcome"] == "denied"
        assert call.kwargs["details"]["allowed"] is False

    def test_missing_decision_attrs_use_defaults(
        self, mock_audit_service: Any,
    ) -> None:
        """Empty decision object → details=None values, no crash."""
        decision = type("D", (), {})()  # no attrs
        facade.emit_authorization_decision(
            decision=decision,
            principal="system",
            resource="api:internal",
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["event"] == "authorization.decision"
        assert call.kwargs["details"]["allowed"] is None


class TestEmitWafEvaluation:
    """Pattern A: WafDecision + outbound context."""

    def test_allowed_request(self, mock_audit_service: Any) -> None:
        decision = type("D", (), {
            "host": "api.example.com",
            "allowed": True,
            "reason": "rule_pass",
        })()
        facade.emit_waf_evaluation(
            decision=decision,
            plugin="core.waf",
            method="GET",
            url="https://api.example.com/users",
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["event"] == "waf.evaluate"
        assert call.kwargs["actor"] == "core.waf"
        assert call.kwargs["action"] == "GET"
        assert call.kwargs["outcome"] == "success"
        assert call.kwargs["details"]["host"] == "api.example.com"
        assert call.kwargs["details"]["allowed"] is True

    def test_blocked_request(self, mock_audit_service: Any) -> None:
        decision = type("D", (), {
            "host": "evil.example.com",
            "allowed": False,
            "reason": "blocklist_match",
        })()
        facade.emit_waf_evaluation(
            decision=decision,
            plugin="core.waf",
            method="POST",
            url="https://evil.example.com/exfil",
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["outcome"] == "denied"
        assert call.kwargs["details"]["reason"] == "blocklist_match"


class TestEmitCapabilityCheck:
    """Pattern B: capability kwargs (highest traffic — 17 callsites)."""

    def test_granted_basic(self, mock_audit_service: Any) -> None:
        facade.emit_capability_check(
            plugin="routes:orders",
            capability="db.read",
            requested_scope="orders",
            declared_scope="orders",
            outcome="granted",
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["event"] == "capability.check"
        assert call.kwargs["actor"] == "routes:orders"
        assert call.kwargs["resource"] == "db.read"
        assert call.kwargs["outcome"] == "granted"
        assert call.kwargs["details"]["requested_scope"] == "orders"
        # tenant, reason absent from details
        assert "tenant" not in call.kwargs["details"]
        assert "reason" not in call.kwargs["details"]

    def test_denied_with_tenant_and_reason(
        self, mock_audit_service: Any,
    ) -> None:
        facade.emit_capability_check(
            plugin="routes:admin",
            capability="db.write",
            requested_scope="orders",
            declared_scope=None,
            outcome="denied",
            tenant="acme",
            reason="scope_mismatch",
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["outcome"] == "denied"
        assert call.kwargs["details"]["tenant"] == "acme"
        assert call.kwargs["details"]["reason"] == "scope_mismatch"
        assert call.kwargs["details"]["declared_scope"] is None

    def test_custom_event_name(self, mock_audit_service: Any) -> None:
        """Tenant-aware events: capability.allocated, capability.revoked."""
        facade.emit_capability_check(
            plugin="routes:billing",
            capability="db.write",
            requested_scope="invoices",
            declared_scope="invoices",
            outcome="granted",
            tenant="acme",
            event="capability.allocated",
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["event"] == "capability.allocated"


class TestEmitSecretRotation:
    """Pattern C: custom Pydantic event (RotationAuditEvent)."""

    def test_success(self, mock_audit_service: Any) -> None:
        facade.emit_secret_rotation(
            secret_path="vault:secret/api-key",
            rotation_id="rot-123",
            correlation_id="wf-456",
            actor="vault-refresher",
            outcome="success",
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["event"] == "secret.rotation"
        assert call.kwargs["actor"] == "vault-refresher"
        assert call.kwargs["resource"] == "vault:secret/api-key"
        assert call.kwargs["outcome"] == "success"
        assert call.kwargs["details"]["rotation_id"] == "rot-123"
        # error_class absent on success
        assert "error_class" not in call.kwargs["details"]

    def test_failure_with_error_class(self, mock_audit_service: Any) -> None:
        facade.emit_secret_rotation(
            secret_path="vault:secret/db",
            rotation_id="rot-789",
            correlation_id="wf-012",
            actor="vault-refresher",
            outcome="failure",
            error_class="VaultConnectionError",
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["outcome"] == "failure"
        assert call.kwargs["details"]["error_class"] == "VaultConnectionError"


class TestEmitAiWorkspace:
    """Pattern A: dict-based (workspace_manager)."""

    def test_basic_event(self, mock_audit_service: Any) -> None:
        facade.emit_ai_workspace({
            "event": "workspace.create",
            "actor": "user:alice",
            "resource": "ws-1",
            "action": "create",
            "outcome": "success",
            "isolation_level": "strict",
        })
        call = mock_audit_service.emit.call_args
        assert call.kwargs["event"] == "workspace.create"
        assert call.kwargs["actor"] == "user:alice"
        assert call.kwargs["resource"] == "ws-1"
        # isolation_level passes through to details (not in canonical kwargs)
        assert call.kwargs["details"]["isolation_level"] == "strict"

    def test_missing_keys_default(self, mock_audit_service: Any) -> None:
        """Empty dict → safe defaults, no crash."""
        facade.emit_ai_workspace({})
        call = mock_audit_service.emit.call_args
        assert call.kwargs["event"] == "ai_workspace.event"
        assert call.kwargs["actor"] == "system"
        assert call.kwargs["details"] is None

    def test_filters_canonical_keys(self, mock_audit_service: Any) -> None:
        """Canonical keys (actor/resource/action/outcome) NOT duplicated в details."""
        facade.emit_ai_workspace({
            "event": "workspace.delete",
            "actor": "user:bob",
            "resource": "ws-2",
            "action": "delete",
            "outcome": "success",
            "extra_field": "extra_value",
        })
        call = mock_audit_service.emit.call_args
        details = call.kwargs["details"]
        assert "actor" not in details
        assert "resource" not in details
        assert "action" not in details
        assert "outcome" not in details
        assert details["extra_field"] == "extra_value"


class TestEmitAuditSafe:
    """Pattern E/G: _safe variant — never raises."""

    def test_success(self, mock_audit_service: Any) -> None:
        facade.emit_audit_safe(
            event="pii.tokenize",
            action="tokenize",
            outcome="success",
            details={"tokens": 5},
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["event"] == "pii.tokenize"
        assert call.kwargs["outcome"] == "success"
        assert call.kwargs["details"]["tokens"] == 5
        # _safe never returns the coroutine directly (returns mock here,
        # but production returns None или coroutine — never raised).

    def test_severity_and_extra(self, mock_audit_service: Any) -> None:
        facade.emit_audit_safe(
            event="agent.tool.error",
            outcome="failure",
            severity="error",
            extra={"tool_name": "web_search"},
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["details"]["severity"] == "error"
        assert call.kwargs["details"]["tool_name"] == "web_search"

    def test_never_raises_on_emit_failure(self) -> None:
        """_safe: emit_audit raises → helper returns None, doesn't propagate."""
        with patch(
            "src.backend.core.audit.facade._base.get_unified_audit_service",
            side_effect=RuntimeError("service unavailable"),
        ):
            # Should not raise
            result = facade.emit_audit_safe(
                event="pii.tokenize",
                outcome="failure",
            )
            assert result is None


class TestEmitBankingAudit:
    """Pattern F: module-level bank args."""

    def test_success(self, mock_audit_service: Any) -> None:
        facade.emit_banking_audit(
            event="banking.kyc_aml.verify",
            processor="credit",
            params={"user_id": "u-1"},
            result={"score": 750},
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["event"] == "banking.kyc_aml.verify"
        assert call.kwargs["actor"] == "credit"
        assert call.kwargs["outcome"] == "success"
        assert call.kwargs["details"]["processor"] == "credit"
        assert call.kwargs["details"]["result"] == {"score": 750}
        assert "error" not in call.kwargs["details"]

    def test_error(self, mock_audit_service: Any) -> None:
        facade.emit_banking_audit(
            event="banking.identity.verify",
            processor="identity",
            params={"doc_id": "d-1"},
            error="timeout",
        )
        call = mock_audit_service.emit.call_args
        assert call.kwargs["outcome"] == "failure"
        assert call.kwargs["details"]["error"] == "timeout"


class TestFacadeExports:
    """__all__ completeness — Path A helpers exported."""

    def test_all_helpers_in_dunder_all(self) -> None:
        from src.backend.core.audit.facade import __all__

        for helper in (
            "emit_audit",
            "emit_authorization_decision",
            "emit_waf_evaluation",
            "emit_capability_check",
            "emit_secret_rotation",
            "emit_ai_workspace",
            "emit_audit_safe",
            "emit_banking_audit",
            "AuditService",
            "get_unified_audit_service",
        ):
            assert helper in __all__, f"{helper} missing from __all__"
