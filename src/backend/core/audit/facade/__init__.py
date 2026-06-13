"""S107 W3 — ``core.audit.facade`` package: per-domain audit emit helpers.

Replaces ``core/audit/facade.py`` (394 LOC god-file) с per-domain
split. Каждый helper живёт в отдельном модуле; ``__init__.py``
re-export'ит canonical API для backward compat с callers
(``from src.backend.core.audit.facade import emit_capability_check``
продолжает работать без изменений).

Per-domain modules (S106 W2 Path A → S107 W3 split):

* ``_base`` — ``emit_audit`` (canonical) + ``emit_audit_safe`` (helper);
* ``authorization`` — ``emit_authorization_decision`` (auth gateway);
* ``waf`` — ``emit_waf_evaluation`` (WAF outbound);
* ``capability`` — ``emit_capability_check`` (capability gate);
* ``secrets`` — ``emit_secret_rotation`` (Vault rotation);
* ``ai`` — ``emit_ai_workspace`` (AI workspace manager);
* ``banking`` — ``emit_banking_audit`` (AI banking processors).

References:
* ADR-0187 (S103 closure)
* ``docs/migration/audit-emit-deprecation.md`` (Path A/B/C/D guide)
* ``tools/check_audit_deprecation.py`` (S105 W2 regression guard)
"""

from __future__ import annotations

# Canonical re-exports (backward compat с pre-S107 callers)
from src.backend.core.audit.facade._base import emit_audit, emit_audit_safe
from src.backend.core.audit.facade.ai import emit_ai_workspace
from src.backend.core.audit.facade.authorization import (
    emit_authorization_decision,
)
from src.backend.core.audit.facade.banking import emit_banking_audit
from src.backend.core.audit.facade.capability import emit_capability_check
from src.backend.core.audit.facade.secrets import emit_secret_rotation
from src.backend.core.audit.facade.waf import emit_waf_evaluation
from src.backend.services.audit.audit_service import (  # noqa: F401
    AuditService,
    get_unified_audit_service,
)

__all__ = (
    "AuditService",
    "get_unified_audit_service",
    "emit_audit",
    # Per-domain helpers (S106 W2 Path A)
    "emit_authorization_decision",
    "emit_waf_evaluation",
    "emit_capability_check",
    "emit_secret_rotation",
    "emit_ai_workspace",
    "emit_audit_safe",
    "emit_banking_audit",
)
