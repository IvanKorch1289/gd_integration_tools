"""S67 W1: PEP 420 namespace package для ``src.backend.infrastructure.storage``.

Storage abstractions (object store, filesystem, key-value).

Cycle-81 (D-AUDIT-8101): re-export :mod:`tenant_file_quota` API из
пакета, чтобы callers (включая ``services.storage.facade``) могли
импортировать через canonical path ``from src.backend.infrastructure
.storage import TenantFileQuotaManager``. Раньше модуль был доступен
только через полный dotted-path — invisible для IDE auto-complete
и lint.

Контракт multi-tenant квот:
* :class:`TenantFileQuotaManager` — Redis-counter pattern (D-AUDIT-1507).
* :class:`QuotaConfig` — per-tenant overrides (``set_tenant_config``).
* :class:`QuotaCheckResult` — pre-check result (allowed/reason + usage).
* :func:`get_tenant_file_quota_manager` — DI singleton.
"""

from src.backend.infrastructure.storage.tenant_file_quota import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_FILES,
    QuotaCheckResult,
    QuotaConfig,
    TenantFileQuotaManager,
    get_tenant_file_quota_manager,
)

__all__ = (
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_FILES",
    "QuotaCheckResult",
    "QuotaConfig",
    "TenantFileQuotaManager",
    "get_tenant_file_quota_manager",
)
