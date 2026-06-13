"""S107 W1 — shim: ``infrastructure.database.tenant_filter`` → ``core.tenancy.sqlalchemy_filter``.

DEPRECATED (S107 W1, TD-002 residual): canonical path —
:mod:`src.backend.core.tenancy.sqlalchemy_filter`. Этот shim остаётся
для backward compat с extensions / pre-S107 кодом; new code ДОЛЖЕН
использовать canonical import:

    # canonical (S107+):
    from src.backend.core.tenancy.sqlalchemy_filter import TenantMixin, apply_tenant_filter

    # legacy (deprecated, will be removed в S109+):
    from src.backend.infrastructure.database.tenant_filter import TenantMixin  # noqa: DEPRECATED
"""

from __future__ import annotations

import warnings

from src.backend.core.tenancy.sqlalchemy_filter import (  # noqa: F401  re-export
    TenantMixin,
    _is_tenant_aware,
    apply_tenant_filter,
)

__all__ = ("TenantMixin", "_is_tenant_aware", "apply_tenant_filter")

warnings.warn(
    "src.backend.infrastructure.database.tenant_filter is deprecated; "
    "use src.backend.core.tenancy.sqlalchemy_filter (S107 W1, TD-002).",
    DeprecationWarning,
    stacklevel=2,
)
