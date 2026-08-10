"""Back-compat shim — canonical class moved to core/observability/correlation.

Phase 1a (infra analysis backlog): actual class definitions
moved to core (pure stdlib, no infrastructure dependencies). This
file remains as a thin re-export so existing callers
(``from src.backend.infrastructure.observability.correlation import ...``)
continue to work without changes.

For new code, import directly from core:
    from src.backend.core.observability.correlation import set_correlation_context

For tests, verify: tests/unit/core/observability/test_correlation.py
(or wherever it lives).
"""

from __future__ import annotations

# re-exports are intentional
from src.backend.core.observability.correlation import (
    correlation_id_var,
    get_correlation_id,
    get_request_id,
    get_tenant_id,
    new_correlation_id,
    request_id_var,
    set_correlation_context,
    tenant_id_var,
)

__all__ = (
    "correlation_id_var",
    "get_correlation_id",
    "get_request_id",
    "get_tenant_id",
    "new_correlation_id",
    "request_id_var",
    "set_correlation_context",
    "tenant_id_var",
)
