"""Policy — OPA + Casbin двухуровневая авторизация (ADR-012).

- OPA (Open Policy Agent): data-level policy, декларативные правила
  Rego на уровне маршрута/payload.
- Casbin: app-level RBAC/ABAC — роли пользователей и ресурсы.
"""

from app.infrastructure.policy.opa import OPAClient, PolicyDecision
from app.infrastructure.policy.casbin_adapter import CasbinAdapter

__all__ = ("OPAClient", "PolicyDecision", "CasbinAdapter")
