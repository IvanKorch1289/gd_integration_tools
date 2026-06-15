from __future__ import annotations

"""Authorization gateway package (S60 W4 decomp from authorization_gateway.py 530 LOC).

9 methods decomposed в 4 mixin files + state.py:
- ``audit_mixin.py`` (1): _emit_audit
- ``casbin_mixin.py`` (1): casbin_step
- ``opa_mixin.py`` (1): opa_step
- ``permission_mixin.py`` (1): permission_step
- ``state.py``: AuthorizationReason + AuthorizationDecision

Core (5) остается в __init__.py: __init__, authorize (91 LOC, BIG), _finalize_deny, _build_decision, _is_enabled.

Backward-compat: ``from src.backend.core.security.authorization_gateway import AuthorizationGateway`` works.
"""


from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import uuid
from collections.abc import Sequence

from src.backend.core.interfaces.capability_gateway import CapabilityGatewayProtocol
from src.backend.core.logging import get_logger

_logger = get_logger("core.security.authorization_gateway")

from src.backend.core.security.authorization_gateway.audit_mixin import (
    AuditMixin,  # S60 W4: MRO
)
from src.backend.core.security.authorization_gateway.casbin_mixin import (
    CasbinMixin,  # S60 W4: MRO
)
from src.backend.core.security.authorization_gateway.opa_mixin import (
    OpaMixin,  # S60 W4: MRO
)
from src.backend.core.security.authorization_gateway.permission_mixin import (
    PermissionMixin,  # S60 W4: MRO
)
from src.backend.core.security.authorization_gateway.state import (
    AuthorizationDecision,  # S60 W4: re-export
    AuthorizationReason,  # S60 W4: re-export
)

__all__ = ("AuthorizationGateway", "AuthorizationReason", "AuthorizationDecision")


class AuthorizationGateway(AuditMixin, CasbinMixin, OpaMixin, PermissionMixin):
    """Authorization gateway (4 mixins = 4 methods + 5 core)."""

    __slots__ = ()

    def __init__(
        self,
        *,
        capability_gateway: CapabilityGatewayProtocol,
        policies: Sequence[PolicyDecider] = (),
        audit_callback: AuditCallback | None = None,
        enabled: bool | None = None,
    ) -> None:
        self._capability_gateway = capability_gateway
        self._policies: tuple[PolicyDecider, ...] = tuple(policies)
        self._audit = audit_callback
        self._enabled = enabled  # None → читать feature-flag в authorize()

    async def authorize(
        self,
        *,
        principal: str,
        resource: str,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> AuthorizationDecision:
        """Принять решение по chain (capability → policies).

        Args:
            principal: Идентификатор запрашивающего (plugin / user).
            resource: Имя ресурса (``capability_name`` / endpoint path).
            action: Действие (``check`` / ``read`` / ``write``).
            context: Произвольный bag (``correlation_id``, ``scope``,
                ``tenant_id``, ``trace_id``).

        Returns:
            AuthorizationDecision с reason-chain.
        """
        ctx = dict(context or {})
        correlation_id = str(ctx.get("correlation_id") or uuid.uuid4())
        ctx["correlation_id"] = correlation_id

        if not self._is_enabled():
            reason = AuthorizationReason(
                source="feature_flag",
                outcome="allow",
                detail="authz_gateway_enabled=False",
            )
            return self._build_decision(
                allowed=True,
                correlation_id=correlation_id,
                reasons=(reason,),
                principal=principal,
                resource=resource,
                action=action,
            )

        reasons: list[AuthorizationReason] = []

        # 1. Capability gateway: единственная обязательная policy.
        try:
            self._capability_gateway.check(principal, resource, ctx.get("scope"))
            reasons.append(
                AuthorizationReason(source="capability_gateway", outcome="allow")
            )
        except Exception as exc:
            reason = AuthorizationReason(
                source="capability_gateway",
                outcome="deny",
                detail=f"{type(exc).__name__}: {exc}",
            )
            return self._finalize_deny(
                principal=principal,
                resource=resource,
                action=action,
                correlation_id=correlation_id,
                reasons=tuple([*reasons, reason]),
            )

        # 2. Доп. policies (Casbin / OPA / custom) — short-circuit на deny.
        for policy in self._policies:
            try:
                reason = await policy(principal, resource, action, ctx)
            except Exception as exc:
                reason = AuthorizationReason(
                    source=getattr(policy, "__name__", "policy"),
                    outcome="deny",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            reasons.append(reason)
            if reason.outcome != "allow":
                return self._finalize_deny(
                    principal=principal,
                    resource=resource,
                    action=action,
                    correlation_id=correlation_id,
                    reasons=tuple(reasons),
                )

        decision = self._build_decision(
            allowed=True,
            correlation_id=correlation_id,
            reasons=tuple(reasons),
            principal=principal,
            resource=resource,
            action=action,
        )
        self._emit_audit(decision)
        return decision

    def _finalize_deny(
        self,
        *,
        principal: str,
        resource: str,
        action: str,
        correlation_id: str,
        reasons: tuple[AuthorizationReason, ...],
    ) -> AuthorizationDecision:
        decision = self._build_decision(
            allowed=False,
            correlation_id=correlation_id,
            reasons=reasons,
            principal=principal,
            resource=resource,
            action=action,
        )
        self._emit_audit(decision)
        return decision

    def _build_decision(
        self,
        *,
        allowed: bool,
        correlation_id: str,
        reasons: tuple[AuthorizationReason, ...],
        principal: str,
        resource: str,
        action: str,
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            allowed=allowed,
            correlation_id=correlation_id,
            reasons=reasons,
            principal=principal,
            resource=resource,
            action=action,
        )

    def _is_enabled(self) -> bool:
        """Источник: явный конструктор или ``feature_flags``."""
        if self._enabled is not None:
            return self._enabled
        try:
            from src.backend.core.feature_flags import get_feature_flag_service

            return get_feature_flag_service().is_enabled("authz_gateway_enabled")
        except Exception as _:
            return False
