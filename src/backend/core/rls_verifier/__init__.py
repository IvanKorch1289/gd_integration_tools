"""Tenant/RLS Verifier — multi-tenancy safety (Wave 4 P0 #36).

Проблема (EP-R1):
    Возможна утечка данных между тенантами:
    - Забытый WHERE tenant_id = ? → cross-tenant read.
    - Race condition в cache key.
    - Routing-ошибка при multi-tenant запросе.

    Без property-based тестов это обнаруживается только в prod.

Решение:
    ``RLSVerifier`` + ``TenantIsolationChecker``:

    1. ``TenantContext`` — dataclass для текущего tenant scope.
    2. ``RLSVerifier.verify_query(query, tenant_context)``:
       - Static analysis: требуется ``WHERE tenant_id = ?`` clause.
       - Reject cross-tenant queries.
    3. ``TenantIsolationChecker.run_matrix(tests)``:
       - Property-based: matrix of (tenant_a, tenant_b) pairs.
       - Verify no cross-tenant leakage.

Использование::

    from src.backend.core.rls_verifier import (
        RLSVerifier, TenantContext, get_rls_verifier,
    )

    verifier = get_rls_verifier()
    query = "SELECT * FROM orders WHERE tenant_id = :tenant"
    ctx = TenantContext(tenant_id="t1", user_id="u1")

    if verifier.verify_query(query, ctx):
        result = execute(query, ctx)
"""

from __future__ import annotations

from src.backend.core.rls_verifier.verifier import (
    IsolationTestCase,
    IsolationTestResult,
    RLSVerifier,
    TenantContext,
    TenantIsolationChecker,
    get_rls_verifier,
)

__all__ = (
    "IsolationTestCase",
    "IsolationTestResult",
    "RLSVerifier",
    "TenantContext",
    "TenantIsolationChecker",
    "get_rls_verifier",
)
