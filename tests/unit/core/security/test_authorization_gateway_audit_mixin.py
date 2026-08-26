"""S57 W1 — Unit-тесты AuditMixin (_emit_audit).

Покрывает все 4 code-path'а из ``audit_mixin.py:19-39``:
1. self._audit is None → no-op (early return)
2. self._audit is set → audit callback invoked с allow-decision payload
3. self._audit is set → audit callback invoked с deny-decision payload
   (verifies "allow"/"deny" mapping в outcome)
4. self._audit raises → exception log'd, не propagates

Часть S57 W1 coverage ratchet (+0.1pp по ADR-0261).
До этого теста module_whitelist 100%, ip_restriction_store 94%,
audit_mixin 0% (39 stmts / 12 branches без тестов).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.backend.core.security.authorization_gateway.audit_mixin import AuditMixin
from src.backend.core.security.authorization_gateway.state import (
    AuthorizationDecision,
    AuthorizationReason,
)


def _make_decision(
    *, allowed: bool, correlation_id: str = "corr-1"
) -> AuthorizationDecision:
    """Build minimal AuthorizationDecision for tests."""
    return AuthorizationDecision(
        allowed=allowed,
        correlation_id=correlation_id,
        reasons=(
            AuthorizationReason(source="policy-A", outcome="allow", detail=None),
        ),
        principal="plugin-x",
        resource="test-resource",
        action="read",
    )


class _Gateway:
    """Minimal host for AuditMixin (provides Protocol-required slots)."""

    def __init__(self, audit: Callable[[dict[str, Any]], None] | None) -> None:
        self._audit = audit


class _TestGateway(AuditMixin, _Gateway):
    """Concrete subclass для прокидывания mixin + host attrs."""


def test_emit_audit_returns_early_when_audit_is_none() -> None:
    """_emit_audit: no-op когда ``self._audit is None`` (L21-22 early return)."""
    gw = _TestGateway(audit=None)
    decision = _make_decision(allowed=True)
    # Should not raise (early return path)
    gw._emit_audit(decision)


def test_emit_audit_calls_callback_with_allow_payload() -> None:
    """_emit_audit: invokes callback with allow-payload когда allowed=True."""
    captured: list[dict[str, Any]] = []

    def audit_callback(payload: dict[str, Any]) -> None:
        captured.append(payload)

    gw = _TestGateway(audit=audit_callback)
    decision = _make_decision(allowed=True, correlation_id="corr-allow")
    gw._emit_audit(decision)

    assert len(captured) == 1
    payload = captured[0]
    assert payload["event"] == "authorization.decision"
    assert payload["correlation_id"] == "corr-allow"
    assert payload["principal"] == "plugin-x"
    assert payload["resource"] == "test-resource"
    assert payload["action"] == "read"
    assert payload["outcome"] == "allow"
    assert len(payload["reasons"]) == 1
    assert payload["reasons"][0]["source"] == "policy-A"
    assert payload["reasons"][0]["outcome"] == "allow"


def test_emit_audit_calls_callback_with_deny_payload() -> None:
    """_emit_audit: maps ``allowed=False`` → outcome='deny' (L31 ternary)."""
    captured: list[dict[str, Any]] = []

    def audit_callback(payload: dict[str, Any]) -> None:
        captured.append(payload)

    gw = _TestGateway(audit=audit_callback)
    decision = _make_decision(allowed=False, correlation_id="corr-deny")
    gw._emit_audit(decision)

    assert captured[0]["outcome"] == "deny"
    assert captured[0]["correlation_id"] == "corr-deny"


def test_emit_audit_swallows_callback_exceptions() -> None:
    """_emit_audit: when callback raises, exception is logged, not re-raised."""
    def failing_audit(payload: dict[str, Any]) -> None:
        raise RuntimeError("audit backend down")

    gw = _TestGateway(audit=failing_audit)
    decision = _make_decision(allowed=True)
    # Should NOT raise — exception swallowed via ``except Exception as _``
    # with _logger.exception (L38-39)
    gw._emit_audit(decision)


def test_emit_audit_includes_reasons_chain() -> None:
    """_emit_audit: maps each AuthorizationReason to dict (L32-35)."""
    captured: list[dict[str, Any]] = []

    def audit_callback(payload: dict[str, Any]) -> None:
        captured.append(payload)

    gw = _TestGateway(audit=audit_callback)
    decision = AuthorizationDecision(
        allowed=False,
        correlation_id="corr-multi",
        reasons=(
            AuthorizationReason(source="policy-X", outcome="allow"),
            AuthorizationReason(source="policy-Y", outcome="deny", detail="unauthorized"),
            AuthorizationReason(source="policy-Z", outcome="deny", detail=None),
        ),
        principal="svc-1",
        resource="db-table",
        action="write",
    )
    gw._emit_audit(decision)

    assert len(captured[0]["reasons"]) == 3
    assert captured[0]["reasons"][0] == {
        "source": "policy-X", "outcome": "allow", "detail": None,
    }
    assert captured[0]["reasons"][1] == {
        "source": "policy-Y", "outcome": "deny", "detail": "unauthorized",
    }
    assert captured[0]["reasons"][2]["source"] == "policy-Z"
