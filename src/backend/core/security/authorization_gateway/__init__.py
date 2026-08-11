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

from __future__ import annotations as annotations

from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Any as Any

if TYPE_CHECKING:
    pass

import uuid
from collections.abc import Sequence as Sequence

from src.backend.core.interfaces.capability_gateway import (
    CapabilityGatewayProtocol as CapabilityGatewayProtocol,
)
from src.backend.core.logging import get_logger as get_logger
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
    AuditCallback,  # S60 W4: re-export
    AuthorizationDecision,  # S60 W4: re-export
    AuthorizationReason,  # S60 W4: re-export
    PolicyDecider,  # S60 W4: re-export
)
from src.backend.core.utils.metrics_registry import metrics_registry as metrics_registry

__all__ = (
    "AuditCallback",
    "AuthorizationDecision",
    "AuthorizationGateway",
    "AuthorizationReason",
    "PolicyDecider",
    # Round 88: lazy resolver для non-Request контекста (Sprint 1 K5).
    # Использует app-state singleton из composition root + fallback на None
    # (если app не зарегистрирован, при ошибках доступа).
    "get_authorization_gateway",
)


# ────────────────── Prometheus metrics (cycle 33 B-01/B-03) ──────────────────
# B-01/B-03 fix (cycle 33): authz fail-open → deny-by-default.
# Counter для engine-failure visibility в ``check()`` (sync path).
# Идемпотентная регистрация через ``metrics_registry`` singleton.
_logger = get_logger("core.security.authorization_gateway")
authz_check_engine_failed_total = metrics_registry.counter(
    "authz_check_engine_failed_total",
    "Failed AuthorizationGateway.check() engine dispatches (casbin/opa).",
    labels=("engine",),
)


def get_authorization_gateway() -> AuthorizationGateway | None:
    """Lazy resolver для :class:`AuthorizationGateway` singleton.

    Round 88 (Sprint 1 K5): non-Request context — для CLI commands,
    background workers, scheduler callbacks. Returns ``None`` если
    app не зарегистрирован через ``register_app_state`` (fail-open
    только в dev/test, в production app всегда зарегистрирован).

    Returns:
        :class:`AuthorizationGateway` singleton или ``None``.

    """
    try:
        from src.backend.core.di.app_state import get_app_ref

        app = get_app_ref()
    except (ImportError, AttributeError, RuntimeError) as app_exc:
        # cycle-9/D-AUDIT-1036: narrow exceptions + observability.
        # ImportError — get_app_ref missing, AttributeError — API
        # change, RuntimeError — app_state unavailable.
        import logging
        logging.getLogger(__name__).debug(
            "authorization_gateway.app_state_fallback",
            extra={"error": str(app_exc)},
        )
        return None
    if app is None:
        return None
    return getattr(app.state, "authorization_gateway", None)


class AuthorizationGateway(AuditMixin, CasbinMixin, OpaMixin, PermissionMixin):
    """Authorization gateway (4 mixins = 4 methods + 5 core)."""

    __slots__ = ("_audit", "_capability_gateway", "_enabled", "_policies")

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
        # S193 fix: in-memory policy storage для sync check/add_policy/remove_policy.
        # Используется как fallback когда нет OPA/Casbin backend.
        self._in_memory_policies: dict[tuple[str, str, str], bool] = {}

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
                AuthorizationReason(source="capability_gateway", outcome="allow"),
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
                reasons=(*reasons, reason),
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

    # S193 fix: sync policy API for AuthorizationFacade compatibility.
    # Был silent AttributeError → facade вызывал nonexistent methods.
    # Теперь: fallback to in-memory policy storage + check additional mixins.
    def check(
        self,
        subject: str,
        action: str,
        resource: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Sync policy check (S193).

        Delegates to:
        1. Casbin step (if `casbin_step` is registered)
        2. OPA step (if `opa_step` is registered)
        3. In-memory policy storage (fallback)

        Args:
            subject: User/service identity.
            action: Action (e.g., ``"read"``).
            resource: Resource (e.g., ``"document:123"``).
            context: Optional context dict.

        Returns:
            True если any matching policy allows.

        """
        # 1. In-memory fallback
        key = (subject, action, resource)
        if key in self._in_memory_policies:
            return self._in_memory_policies[key]

        # 2. Try Casbin step if registered
        # B-03 fix (cycle 33): silent ``except: pass`` → warning + counter.
        # Раньше exception из Casbin engine'а глохся и в логах ничего не
        # появлялось — observability gap для security-path. Теперь WARNING
        # с engine + типом исключения, и ``authz_check_engine_failed_total``
        # растёт по ``engine="casbin"``, чтобы алерты видели деградацию.
        try:
            casbin_result = self._casbin_check(subject, action, resource)
            if casbin_result is not None:
                return casbin_result
        except Exception as exc:
            authz_check_engine_failed_total.labels(engine="casbin").inc()
            _logger.warning(
                "authz.check() engine=casbin failed: %s",
                exc,
            )

        # 3. Try OPA step if registered
        # B-03 fix (cycle 33): см. выше — same observability gap, та же
        # правка для OPA engine'а (``engine="opa"``).
        try:
            opa_result = self._opa_check(subject, action, resource, context)
            if opa_result is not None:
                return opa_result
        except Exception as exc:
            authz_check_engine_failed_total.labels(engine="opa").inc()
            _logger.warning(
                "authz.check() engine=opa failed: %s",
                exc,
            )

        # 4. Default deny (fail-closed)
        return False

    def add_policy(
        self,
        subject: str,
        action: str,
        resource: str,
        effect: str = "allow",
    ) -> bool:
        """Add policy rule (S193 fix).

        Args:
            subject: User/service identity.
            action: Action.
            resource: Resource.
            effect: ``"allow"`` или ``"deny"``.

        Returns:
            True если policy добавлен.

        """
        try:
            allowed = effect.lower() == "allow"
            key = (subject, action, resource)
            self._in_memory_policies[key] = allowed
            return True
        except (AttributeError, TypeError, ValueError) as policy_exc:
            # cycle-9/D-AUDIT-990: narrow exceptions + observability.
            # AttributeError — effect missing, TypeError — wrong type,
            # ValueError — invalid effect value.
            import logging
            logging.getLogger(__name__).debug(
                "authorization_gateway.add_policy_failed",
                extra={"error": str(policy_exc)},
            )
            return False

    def remove_policy(
        self,
        subject: str,
        action: str,
        resource: str,
    ) -> bool:
        """Remove policy rule (S193 fix).

        Returns:
            True если policy удалён.

        """
        try:
            key = (subject, action, resource)
            if key in self._in_memory_policies:
                del self._in_memory_policies[key]
                return True
            return False
        except (KeyError, AttributeError, TypeError) as rm_exc:
            # cycle-9/D-AUDIT-999: narrow exceptions + observability (mirror
            # D-AUDIT-990 для add_policy).
            # KeyError — key not in dict (rare race), AttributeError —
            # _in_memory_policies API change, TypeError — wrong key type.
            import logging
            logging.getLogger(__name__).debug(
                "authorization_gateway.remove_policy_failed",
                extra={"error": str(rm_exc)},
            )
            return False

    def _casbin_check(
        self, subject: str, action: str, resource: str,
    ) -> bool | None:
        """Internal: try Casbin step if available."""
        from src.backend.core.security.authorization_gateway.casbin_mixin import (
            CasbinMixin,
        )

        if hasattr(CasbinMixin, "_casbin_check"):
            return CasbinMixin._casbin_check(self, subject, action, resource)
        return None

    def _opa_check(
        self,
        subject: str,
        action: str,
        resource: str,
        context: dict[str, Any] | None,
    ) -> bool | None:
        """Internal: try OPA step if available."""
        from src.backend.core.security.authorization_gateway.opa_mixin import OpaMixin

        if hasattr(OpaMixin, "_opa_check"):
            return OpaMixin._opa_check(
                self, subject, action, resource, context,
            )
        return None

    def _is_enabled(self) -> bool:
        """Источник: явный конструктор или ``feature_flags``.

        B-01 fix (cycle 33): invert fail-open → deny-by-default.
        Если lookup фичи упал (Redis down, registry corrupt и т.п.),
        РАНЬШЕ возвращали ``False`` → ``authorize()`` дальше делал
        ``return allowed=True`` без проверок (P0 — обход authz при
        деградации feature-flag service). ТЕПЕРЬ: ERROR-лог + ``True``,
        чтобы шёл нормальный chain (capability check → fail-closed deny
        при исключении). Конструкторский ``_enabled`` имеет приоритет.
        """
        if self._enabled is not None:
            return self._enabled
        try:
            from src.backend.core.feature_flags import get_feature_flag_service

            return get_feature_flag_service().is_enabled("authz_gateway_enabled")
        except Exception as exc:
            _logger.error(
                "authz feature-flag lookup failed; treating as enabled "
                "to preserve deny-by-default chain: %s",
                exc,
            )
            return True
