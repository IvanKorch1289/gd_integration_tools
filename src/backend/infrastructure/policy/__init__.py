"""Policy — OPA + Casbin двухуровневая авторизация (ADR-012).

- OPA (Open Policy Agent): data-level policy, декларативные правила
  Rego на уровне маршрута/payload.
- Casbin: app-level RBAC/ABAC — роли пользователей и ресурсы.
"""

from src.backend.infrastructure.policy.casbin_adapter import CasbinAdapter  # noqa: F401 — re-export
from src.backend.infrastructure.policy.opa import OPAClient, PolicyDecision  # noqa: F401 — re-export

__all__ = ("CasbinAdapter", "OPAClient", "PolicyDecision")
