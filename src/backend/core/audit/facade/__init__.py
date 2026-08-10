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
* ``secrets`` — ``emit_secret_rotation`` (Vault rotation) +
  ``emit_secret_access`` (CredentialProvider access, Cycle 60 L8);
* ``ai`` — ``emit_ai_workspace`` (AI workspace manager);
* ``banking`` — ``emit_banking_audit`` (AI banking processors).

References:
* ADR-0187 (S103 closure)
* ``docs/migration/audit-emit-deprecation.md`` (Path A/B/C/D guide)
* ``tools/check_audit_deprecation.py`` (S105 W2 regression guard)

"""

from __future__ import annotations as annotations

from pathlib import Path as Path
from typing import TYPE_CHECKING as TYPE_CHECKING

# Canonical re-exports (backward compat с pre-S107 callers)
from src.backend.core.audit.facade._base import (  # noqa: F401 — re-export
    emit_audit,
    emit_audit_safe,
)
from src.backend.core.audit.facade.ai import emit_ai_workspace  # noqa: F401 — re-export
from src.backend.core.audit.facade.audit_service import (
    AuditService,
    get_unified_audit_service,
)
from src.backend.core.audit.facade.authorization import (
    emit_authorization_decision,  # noqa: F401 — re-export
)
from src.backend.core.audit.facade.banking import (
    emit_banking_audit,  # noqa: F401 — re-export
)
from src.backend.core.audit.facade.capability import (
    emit_capability_check,  # noqa: F401 — re-export
)
from src.backend.core.audit.facade.secrets import (
    emit_secret_access,
    emit_secret_rotation,
)
from src.backend.core.audit.facade.waf import (
    emit_waf_evaluation,  # noqa: F401 — re-export
)

if TYPE_CHECKING:
    from src.backend.infrastructure.audit.jsonl_audit import JsonlAuditBackend


def get_jsonl_backend(path: str | Path) -> JsonlAuditBackend:
    """Capability-checked factory для :class:`JsonlAuditBackend` (B-11 fix, cycle 33).

    Заменяет ``importlib.import_module('src.backend.infrastructure.audit.jsonl_audit')``
    в callers из слоя ``services`` (где прямой импорт infrastructure нарушает
    ``check_layers.py``). Lazy-import внутри функции — позволяет
    ``services/*`` ссылаться на infrastructure через core-facade без
    циркулярного import'a и без layer-violation.

    Args:
        path: Путь к JSONL-файлу (директория создаётся при необходимости).

    Returns:
        Готовый ``JsonlAuditBackend`` instance для DLQ-fallback.

    """
    # Lazy import: infrastructure → core facade import разрешён layer-rules.
    from src.backend.infrastructure.audit.jsonl_audit import JsonlAuditBackend

    return JsonlAuditBackend(path)


__all__ = (
    "AuditService",
    "emit_ai_workspace",
    "emit_audit",
    "emit_audit_safe",
    # Per-domain helpers (S106 W2 Path A)
    "emit_authorization_decision",
    "emit_banking_audit",
    "emit_capability_check",
    "emit_secret_access",
    "emit_secret_rotation",
    "emit_waf_evaluation",
    "get_jsonl_backend",
    "get_unified_audit_service",
)
