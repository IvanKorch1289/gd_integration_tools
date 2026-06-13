# ruff: noqa: S101
"""S107 W3 — tests для ``core.audit.facade`` package split (TD-008).

Покрытие:

* Все 8 функций re-exported через ``core.audit.facade`` package;
* Per-domain модули импортируются отдельно (authorization, waf,
  capability, secrets, ai, banking);
* ``_base`` экспортирует ``emit_audit`` + ``emit_audit_safe``;
* ``AuditService`` + ``get_unified_audit_service`` re-exported
  из ``services.audit.audit_service`` (S103 W3 pattern);
* Backward compat: ``from src.backend.core.audit.facade import X``
  работает для всех 8 helpers;
* Lazy-load: helper делегирует на ``emit_audit`` (canonical).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ── Package structure ──


def test_facade_package_exists_with_init() -> None:
    """``core/audit/facade`` — package (not module), имеет __init__.py."""
    import src.backend.core.audit.facade as facade_pkg
    assert hasattr(facade_pkg, "__file__") or hasattr(facade_pkg, "__path__")
    # Package должен иметь __path__ (packages have it, modules don't)
    assert hasattr(facade_pkg, "__path__")


def test_facade_package_has_per_domain_submodules() -> None:
    """Package содержит 6 per-domain submodules + _base."""
    import importlib

    expected_modules = [
        "_base",
        "authorization",
        "waf",
        "capability",
        "secrets",
        "ai",
        "banking",
    ]
    for name in expected_modules:
        mod = importlib.import_module(f"src.backend.core.audit.facade.{name}")
        assert mod is not None


# ── Backward compat re-exports ──


def test_all_8_helpers_reexported_from_package() -> None:
    """Все 8 emit_* helpers + AuditService re-exported из package __init__."""
    from src.backend.core.audit.facade import (
        AuditService,
        emit_ai_workspace,
        emit_audit,
        emit_audit_safe,
        emit_authorization_decision,
        emit_banking_audit,
        emit_capability_check,
        emit_secret_rotation,
        emit_waf_evaluation,
        get_unified_audit_service,
    )
    # Smoke: all 10 symbols exist
    assert callable(emit_audit)
    assert callable(emit_audit_safe)
    assert callable(emit_authorization_decision)
    assert callable(emit_waf_evaluation)
    assert callable(emit_capability_check)
    assert callable(emit_secret_rotation)
    assert callable(emit_ai_workspace)
    assert callable(emit_banking_audit)
    assert AuditService is not None
    assert callable(get_unified_audit_service)


def test_audit_service_reexport_preserves_identity() -> None:
    """``AuditService`` из facade = ``AuditService`` из services.audit (identity)."""
    from src.backend.core.audit.facade import AuditService as Facade_AuditService
    from src.backend.services.audit.audit_service import (
        AuditService as Canonical_AuditService,
    )
    assert Facade_AuditService is Canonical_AuditService


# ── Per-domain module isolation ──


def test_capability_helper_lives_in_capability_submodule() -> None:
    """``emit_capability_check`` импортируется из ``facade.capability`` напрямую."""
    from src.backend.core.audit.facade import emit_capability_check as Facade
    from src.backend.core.audit.facade.capability import (
        emit_capability_check as Submodule,
    )
    # Identity check: facade.__init__ re-export = same function
    assert Facade is Submodule


def test_authorization_helper_lives_in_authorization_submodule() -> None:
    from src.backend.core.audit.facade import emit_authorization_decision as Facade
    from src.backend.core.audit.facade.authorization import (
        emit_authorization_decision as Submodule,
    )
    assert Facade is Submodule


def test_waf_helper_lives_in_waf_submodule() -> None:
    from src.backend.core.audit.facade import emit_waf_evaluation as Facade
    from src.backend.core.audit.facade.waf import emit_waf_evaluation as Submodule
    assert Facade is Submodule


def test_secrets_helper_lives_in_secrets_submodule() -> None:
    from src.backend.core.audit.facade import emit_secret_rotation as Facade
    from src.backend.core.audit.facade.secrets import (
        emit_secret_rotation as Submodule,
    )
    assert Facade is Submodule


def test_ai_helper_lives_in_ai_submodule() -> None:
    from src.backend.core.audit.facade import emit_ai_workspace as Facade
    from src.backend.core.audit.facade.ai import emit_ai_workspace as Submodule
    assert Facade is Submodule


def test_banking_helper_lives_in_banking_submodule() -> None:
    from src.backend.core.audit.facade import emit_banking_audit as Facade
    from src.backend.core.audit.facade.banking import (
        emit_banking_audit as Submodule,
    )
    assert Facade is Submodule


def test_base_module_exports_emit_audit_and_safe() -> None:
    """``_base`` module содержит ``emit_audit`` + ``emit_audit_safe``."""
    from src.backend.core.audit.facade._base import emit_audit, emit_audit_safe
    assert callable(emit_audit)
    assert callable(emit_audit_safe)


# ── Helper delegates to canonical emit_audit ──


def test_capability_check_helper_delegates_to_emit_audit() -> None:
    """``emit_capability_check`` вызывает ``emit_audit`` с правильными kwargs."""
    from src.backend.core.audit.facade import emit_capability_check

    with patch(
        "src.backend.core.audit.facade._base.get_unified_audit_service"
    ) as mock_svc:
        mock_audit = MagicMock()
        mock_svc.return_value = mock_audit
        mock_audit.emit.return_value = "ok"

        result = emit_capability_check(
            plugin="core.test",
            capability="db.read",
            requested_scope="orders",
            declared_scope="orders",
            outcome="granted",
            tenant="t1",
            reason=None,
        )

    assert result == "ok"
    mock_audit.emit.assert_called_once()
    call_kwargs = mock_audit.emit.call_args.kwargs
    assert call_kwargs["event"] == "capability.check"
    assert call_kwargs["actor"] == "core.test"
    assert call_kwargs["resource"] == "db.read"
    assert call_kwargs["action"] == "check"
    assert call_kwargs["outcome"] == "granted"
    assert call_kwargs["details"]["plugin"] == "core.test"
    assert call_kwargs["details"]["capability"] == "db.read"
    assert call_kwargs["details"]["tenant"] == "t1"


def test_authorization_decision_helper_translates_dataclass() -> None:
    """``emit_authorization_decision`` extracts ``allowed``/``reason`` from decision."""

    from src.backend.core.audit.facade import emit_authorization_decision

    # Fake decision dataclass
    class FakeDecision:
        allowed = True
        reason = "matched policy"
        matched_policy = "policy_x"
        scope_checked = "orders"
        evaluated_at = "2026-06-13T12:00:00Z"

    with patch(
        "src.backend.core.audit.facade._base.get_unified_audit_service"
    ) as mock_svc:
        mock_audit = MagicMock()
        mock_svc.return_value = mock_audit
        emit_authorization_decision(
            decision=FakeDecision(),
            principal="user:alice",
            resource="orders",
        )

    call_kwargs = mock_audit.emit.call_args.kwargs
    assert call_kwargs["event"] == "authorization.decision"
    assert call_kwargs["actor"] == "user:alice"
    assert call_kwargs["outcome"] == "success"
    assert call_kwargs["details"]["allowed"] is True
    assert call_kwargs["details"]["matched_policy"] == "policy_x"


def test_audit_safe_swallows_exceptions() -> None:
    """``emit_audit_safe`` возвращает None при исключении в ``emit_audit``."""
    from src.backend.core.audit.facade import emit_audit_safe

    with patch("src.backend.core.audit.facade._base.emit_audit") as mock_emit:
        mock_emit.side_effect = RuntimeError("audit service down")
        result = emit_audit_safe(event="test.event", action="noop")

    # _safe variant: не raise, возвращает None
    assert result is None
    mock_emit.assert_called_once()


def test_ai_workspace_helper_passes_event_dict_through() -> None:
    """``emit_ai_workspace`` принимает dict и извлекает event/actor/etc."""
    from src.backend.core.audit.facade import emit_ai_workspace

    with patch(
        "src.backend.core.audit.facade._base.get_unified_audit_service"
    ) as mock_svc:
        mock_audit = MagicMock()
        mock_svc.return_value = mock_audit
        emit_ai_workspace(
            {
                "event": "workspace.create",
                "actor": "user:bob",
                "resource": "ws-1",
                "custom_field": "preserved",
            }
        )

    call_kwargs = mock_audit.emit.call_args.kwargs
    assert call_kwargs["event"] == "workspace.create"
    assert call_kwargs["actor"] == "user:bob"
    # custom_field preserved в details
    assert call_kwargs["details"]["custom_field"] == "preserved"


def test_banking_audit_helper_maps_error_to_outcome() -> None:
    """``emit_banking_audit``: error != None → outcome='failure'."""
    from src.backend.core.audit.facade import emit_banking_audit

    with patch(
        "src.backend.core.audit.facade._base.get_unified_audit_service"
    ) as mock_svc:
        mock_audit = MagicMock()
        mock_svc.return_value = mock_audit
        emit_banking_audit(
            event="banking.kyc_aml.verify",
            processor="identity",
            params={"doc_id": "x"},
            error="timeout",
        )

    call_kwargs = mock_audit.emit.call_args.kwargs
    assert call_kwargs["outcome"] == "failure"
    assert call_kwargs["details"]["error"] == "timeout"
    assert call_kwargs["details"]["processor"] == "identity"
