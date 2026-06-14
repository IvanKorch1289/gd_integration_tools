"""Backward-compat shim для ``AuditService`` (S113 W1).

Канонический домен класса перенесён в :mod:`src.backend.core.audit.facade.audit_service`
(завершает S103 W3 split). Этот модуль остаётся как thin re-export — не
ломает 14 существующих consumers, импортирующих
``from src.backend.services.audit.audit_service import AuditService``.

См. ADR-0199 (S113 W5) — backward-compat policy для audit facade.
"""

from __future__ import annotations

from src.backend.core.audit.facade.audit_service import (
    AuditService,
    get_unified_audit_service,
)

__all__ = ("AuditService", "get_unified_audit_service")
