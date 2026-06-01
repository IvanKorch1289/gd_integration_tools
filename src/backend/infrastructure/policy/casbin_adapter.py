"""Casbin adapter — RBAC/ABAC на уровне приложения.

Модель — RBAC с ролями/ресурсами/действиями. Конфигурация в
``policies/casbin_model.conf``; policy-store — file или DB.
"""

from __future__ import annotations

import logging

__all__ = ("CasbinAdapter",)

logger = logging.getLogger("policy.casbin")


class CasbinAdapter:
    """Тонкая обёртка над casbin Enforcer."""

    def __init__(self, model_path: str, policy_path: str | None = None) -> None:
        self.model_path = model_path
        self.policy_path = policy_path
        self._enforcer = None  # type: Any

    def _ensure_enforcer(self):
        if self._enforcer is None:
            try:
                import casbin

                if self.policy_path:
                    self._enforcer = casbin.Enforcer(self.model_path, self.policy_path)
                else:
                    self._enforcer = casbin.Enforcer(self.model_path)
            except ImportError:
                logger.warning("casbin не установлен — RBAC отключён (deny-all)")
                return None
        return self._enforcer

    def enforce(self, subject: str, resource: str, action: str) -> bool:
        """True — action разрешён, False — запрещён."""
        enforcer = self._ensure_enforcer()
        if enforcer is None:
            return False
        try:
            return bool(enforcer.enforce(subject, resource, action))
        except Exception as exc:
            logger.error("Casbin enforce fail: %s", exc)
            return False

    def add_role(self, user: str, role: str) -> bool:
        enforcer = self._ensure_enforcer()
        if enforcer is None:
            return False
        return bool(enforcer.add_role_for_user(user, role))

    def add_policy(self, role: str, resource: str, action: str) -> bool:
        enforcer = self._ensure_enforcer()
        if enforcer is None:
            return False
        return bool(enforcer.add_policy(role, resource, action))
