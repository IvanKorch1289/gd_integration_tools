"""B-12 fix (cycle 37): Casbin-based PolicyDecider factory.

Тонкая обёртка над :func:`AuthorizationGateway.casbin_step`. Composition-root-у
и DI-провайдерам — один вызов для прокидывания Casbin (RBAC/ABAC) в цепочку
:class:`AuthorizationGateway`:

>>> policies = [build_casbin_policy_decider(casbin)]
>>> AuthorizationGateway(..., policies=policies)

Слой ``core`` не импортирует ``infrastructure`` — Casbin-enforcer передаётся
через ``Any`` (duck-type: ``enforce(sub, obj, act, tenant) -> bool``).
Контракт проверяется тестами в ``tests/integration/test_opa_runtime_cycle37.py``.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.security.authorization_gateway import AuthorizationGateway
from src.backend.core.security.authorization_gateway.state import PolicyDecider

__all__ = ("CasbinPolicyDecider", "build_casbin_policy_decider")


def build_casbin_policy_decider(casbin_enforcer: Any) -> PolicyDecider:
    """Создать :data:`PolicyDecider` из Casbin-enforcer-а (B-12 fix, cycle 37).

    Args:
        casbin_enforcer: Enforcer-объект (duck-type
            ``enforce(user_id, resource, action, tenant_id=None) -> bool``).
            Для multi-tenant — ``TenantScopedCasbin`` из
            ``src.backend.infrastructure.policy.casbin_tenant_scoped``.

    Returns:
        :data:`PolicyDecider` callable, ready-to-use в
        ``AuthorizationGateway(..., policies=(...,))``.

    """
    # B-12 fix (cycle 37): composition root delegating к existing фабрике.
    return AuthorizationGateway.casbin_step(casbin_enforcer)


# Краткий alias для DI.
CasbinPolicyDecider = build_casbin_policy_decider
