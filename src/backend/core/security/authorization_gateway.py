"""ADR-NEW-1 (Sprint 17): единый фасад авторизации :class:`AuthorizationGateway`.

Контекст:
    V22 centralization (K-ARCH-1 + K-ARCH-2): до S17 авторизация была
    разбросана между ``CapabilityGate`` (V11.1), Casbin RBAC (планируется),
    OPA policy (планируется) и ad-hoc auth-guard middleware. Это
    приводило к:

    * отсутствию единого ``correlation_id`` на всю chain;
    * дубликации audit-event на разных уровнях;
    * сложности добавления новой policy без изменения 30+ callsites.

Решение:
    :class:`AuthorizationGateway` — асинхронный фасад с операцией
    ``authorize(principal, resource, action, context)``. Композирует
    цепочку policy-движков и возвращает :class:`AuthorizationDecision`
    с цепочкой ``reasons`` (allow / deny + источник).

Цепочка по умолчанию (Sprint 17 scaffold):
    1. :class:`CapabilityGatewayProtocol` (обязателен) — declare/check.
    2. ``CapabilityPolicy`` (опционально, R2) — scope-aware.
    3. ``CasbinAdapter`` (опционально, S18) — RBAC.
    4. ``OPAAdapter`` (опционально, S19) — fine-grained ABAC.

Audit:
    На каждое решение эмитится ``authorization.decision`` event со
    всеми полями ``AuthorizationDecision``. ``correlation_id`` берётся
    из context (если задан) или генерируется через ``uuid4``.

Feature-flag:
    Активация — ``feature_flags.authz_gateway_enabled`` (default-OFF).
    При False ``authorize()`` возвращает ``allow`` без проверок (для
    плавной миграции callsites).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from src.backend.core.interfaces.capability_gateway import CapabilityGatewayProtocol
from src.backend.core.logging import get_logger

__all__ = (
    "AuthorizationDecision",
    "AuthorizationGateway",
    "AuthorizationReason",
    "PolicyDecider",
)

_logger = get_logger("core.security.authorization_gateway")


@dataclass(frozen=True, slots=True)
class AuthorizationReason:
    """Одно звено в reason-chain ``AuthorizationDecision``."""

    source: str
    outcome: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Результат ``authorize()``: allow/deny + reason-chain.

    Attributes:
        allowed: True если все policies в цепочке вернули allow.
        correlation_id: Сквозной идентификатор для трассировки.
        reasons: Цепочка policy-решений по порядку проверки.
        principal: Кто запрашивает (plugin id / user / service).
        resource: Имя ресурса (capability / endpoint / table).
        action: Запрашиваемое действие (read / write / call).
    """

    allowed: bool
    correlation_id: str
    reasons: tuple[AuthorizationReason, ...]
    principal: str
    resource: str
    action: str


AuditCallback = Callable[[dict[str, Any]], None]
PolicyDecider = Callable[
    [str, str, str, dict[str, Any]], Awaitable[AuthorizationReason]
]


class AuthorizationGateway:
    """Единый фасад авторизации (ADR-NEW-1 / S17 K-ARCH-1+2).

    Args:
        capability_gateway: Обязательная реализация
            :class:`CapabilityGatewayProtocol` (обычно CapabilityGate).
        policies: Доп. async-policy в порядке проверки. Каждая —
            ``async def policy(principal, resource, action, context)``
            возвращает :class:`AuthorizationReason`. Остановка на
            первой ``outcome != "allow"``.
        audit_callback: Опц. callback для эмиссии
            ``authorization.decision`` event (см. dict-schema в коде).
        enabled: Включение фасада. По умолчанию читается из
            ``feature_flags.authz_gateway_enabled``. При False
            ``authorize`` возвращает allow без проверок.

    Example:
        >>> from src.backend.core.security.capabilities.gate import CapabilityGate
        >>> gateway = AuthorizationGateway(capability_gateway=CapabilityGate())
        >>> decision = await gateway.authorize(
        ...     principal="example_plugin",
        ...     resource="db.read",
        ...     action="check",
        ...     context={"scope": "users"},
        ... )
        >>> decision.allowed
        True
    """

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
            from src.backend.core.config.features import feature_flags

            return bool(feature_flags.authz_gateway_enabled)
        except Exception as _:
            return False

    def _emit_audit(self, decision: AuthorizationDecision) -> None:
        """Эмиссия ``authorization.decision`` event (best-effort)."""
        if self._audit is None:
            return
        try:
            self._audit(
                {
                    "event": "authorization.decision",
                    "correlation_id": decision.correlation_id,
                    "principal": decision.principal,
                    "resource": decision.resource,
                    "action": decision.action,
                    "outcome": "allow" if decision.allowed else "deny",
                    "reasons": [
                        {"source": r.source, "outcome": r.outcome, "detail": r.detail}
                        for r in decision.reasons
                    ],
                }
            )
        except Exception as _:
            _logger.exception("AuthorizationGateway audit_callback failed")

    # ------------------------------------------------------------------ steps

    @staticmethod
    def casbin_step(casbin_enforcer: Any) -> PolicyDecider:
        """Фабрика :data:`PolicyDecider` для Casbin RBAC step (S18 W3, S-L8-1).

        Args:
            casbin_enforcer: Объект, реализующий duck-type интерфейс
                ``enforce(user_id: str, resource: str, action: str,
                tenant_id: str | None = None) -> bool``. Например
                ``infrastructure.policy.casbin_tenant_scoped.TenantScopedCasbin``.
                Слой ``core`` не импортирует ``infrastructure``, поэтому
                тип — :data:`Any`; контракт enforced через docstring и
                test-suite (``test_authorization_gateway_steps.py``).

        Returns:
            :data:`PolicyDecider`-функция, готовая к добавлению в
            ``AuthorizationGateway(..., policies=(...,))``.

        Поведение:
            * ``ctx["tenant_id"]`` пробрасывается как 4-й аргумент enforce'а.
            * Любое исключение из ``enforce`` → ``deny`` (fail-closed).
            * Возвращаемый ``AuthorizationReason`` имеет ``source="casbin"``.

        Example:
            >>> from infrastructure.policy.casbin_tenant_scoped import TenantScopedCasbin
            >>> casbin = TenantScopedCasbin(base_adapter=...)
            >>> gateway = AuthorizationGateway(
            ...     capability_gateway=gate,
            ...     policies=(AuthorizationGateway.casbin_step(casbin),),
            ... )
        """

        async def _step(
            principal: str, resource: str, action: str, ctx: dict[str, Any]
        ) -> AuthorizationReason:
            tenant_id = ctx.get("tenant_id")
            try:
                allowed = casbin_enforcer.enforce(
                    principal, resource, action, tenant_id=tenant_id
                )
            except Exception as exc:
                return AuthorizationReason(
                    source="casbin",
                    outcome="deny",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            return AuthorizationReason(
                source="casbin",
                outcome="allow" if allowed else "deny",
                detail=None if allowed else "casbin_enforce_denied",
            )

        _step.__name__ = "casbin_step"
        return _step

    @staticmethod
    def opa_step(opa_client: Any, policy_name: str) -> PolicyDecider:
        """Фабрика :data:`PolicyDecider` для OPA runtime-query step (S18 W3, S-L8-2).

        Args:
            opa_client: Объект, реализующий duck-type интерфейс
                ``async query(policy: str, input_doc: dict[str, Any]) -> X``,
                где ``X`` имеет атрибуты ``allow: bool`` и
                ``reasons: list[str]``. Например
                ``infrastructure.policy.opa.OPAClient``. Тип — :data:`Any`
                для соблюдения layer-policy (см. ``casbin_step`` docstring).
            policy_name: Имя rego-package (точки → слэши на стороне клиента),
                например ``"authz/default"`` (см. reference scaffold
                ``infrastructure/policy/opa/policies/authz_default.rego``).

        Returns:
            :data:`PolicyDecider`-функция, готовая к добавлению в
            ``AuthorizationGateway(..., policies=(...,))``.

        Поведение:
            * Проверяет feature-flag ``opa_runtime_query_enabled``:
              при OFF → no-op ``allow`` с пометкой
              ``opa_runtime_query_enabled=False`` (плавная миграция).
            * При ON → формирует ``input_doc`` с ``{principal, resource,
              action, tenant_id, correlation_id}`` из ``ctx`` и делает
              ``await opa_client.query(policy_name, input_doc)``.
            * Любое исключение / сетевая ошибка → ``deny`` (fail-closed,
              consistent с ``OPAClient.query`` deny-by-default policy).

        Example:
            >>> from infrastructure.policy.opa import OPAClient
            >>> opa = OPAClient(base_url="http://opa:8181")
            >>> gateway = AuthorizationGateway(
            ...     capability_gateway=gate,
            ...     policies=(AuthorizationGateway.opa_step(opa, "authz/default"),),
            ... )
        """

        async def _step(
            principal: str, resource: str, action: str, ctx: dict[str, Any]
        ) -> AuthorizationReason:
            try:
                from src.backend.core.config.features import feature_flags

                if not feature_flags.opa_runtime_query_enabled:
                    return AuthorizationReason(
                        source="opa",
                        outcome="allow",
                        detail="opa_runtime_query_enabled=False",
                    )
            except Exception as _:
                return AuthorizationReason(
                    source="opa", outcome="deny", detail="feature_flag_unavailable"
                )

            input_doc = {
                "principal": principal,
                "resource": resource,
                "action": action,
                "tenant_id": ctx.get("tenant_id"),
                "correlation_id": ctx.get("correlation_id"),
            }
            try:
                decision = await opa_client.query(policy_name, input_doc)
            except Exception as exc:
                return AuthorizationReason(
                    source="opa", outcome="deny", detail=f"{type(exc).__name__}: {exc}"
                )

            allow = bool(getattr(decision, "allow", False))
            reasons = list(getattr(decision, "reasons", []) or [])
            detail: str | None = None
            if not allow:
                detail = ",".join(reasons) if reasons else "opa_denied"
            return AuthorizationReason(
                source="opa", outcome="allow" if allow else "deny", detail=detail
            )

        _step.__name__ = "opa_step"
        return _step

    # ------------------------------------------------------------------ permission_step

    @staticmethod
    def permission_step(required_permissions: tuple[str, ...]) -> PolicyDecider:
        """Фабрика :data:`PolicyDecider` для route-level permission check (K3 S19 W3).

        Args:
            required_permissions: Кортеж строк в формате ``"role:<role>"`` или
                ``"scope:<scope>"``, определённый в ``route.toml [security]
                requires_permission``. Пустой кортеж — no-op allow.

        Returns:
            :data:`PolicyDecider`-функция, готовая к добавлению в
            ``AuthorizationGateway(..., policies=(...,))``.

        Поведение:
            * Проверяет feature-flag ``route_authz_requires_permission``:
              при OFF → no-op ``allow`` (для обратной совместимости).
            * При ON → из ``ctx["permissions"]`` (tuple[str, ...]) извлекаются
              фактические permissions-principal'а и проверяется, что
              **все** ``required_permissions`` присутствуют в фактических.
            * Формат permission: префикс ``role:`` или ``scope:`` + имя.
            * Любое исключение / отсутствие ``ctx["permissions"]`` → ``deny``
              (fail-closed) с соответствующим detail.

        Example:
            >>> # route.toml: [security] requires_permission = ["role:admin", "scope:credit.read"]
            >>> gateway = AuthorizationGateway(
            ...     capability_gateway=gate,
            ...     policies=(
            ...         AuthorizationGateway.permission_step(
            ...             ("role:admin", "scope:credit.read")
            ...         ),
            ...     ),
            ... )
        """

        async def _step(
            principal: str, resource: str, action: str, ctx: dict[str, Any]
        ) -> AuthorizationReason:
            # No permissions required → always allow
            if not required_permissions:
                return AuthorizationReason(
                    source="permission",
                    outcome="allow",
                    detail="no_required_permissions",
                )

            # Feature flag check
            try:
                from src.backend.core.config.features import feature_flags

                if not feature_flags.route_authz_requires_permission:
                    return AuthorizationReason(
                        source="permission",
                        outcome="allow",
                        detail="route_authz_requires_permission=False",
                    )
            except Exception as _:
                return AuthorizationReason(
                    source="permission",
                    outcome="deny",
                    detail="feature_flag_unavailable",
                )

            # Extract principal permissions from context
            actual_permissions: tuple[str, ...] = ctx.get("permissions", ())
            if not actual_permissions:
                return AuthorizationReason(
                    source="permission",
                    outcome="deny",
                    detail="no_permissions_in_context",
                )

            # Build set of actual permission strings
            actual_set = set(actual_permissions)

            # Check all required permissions are present
            missing: list[str] = []
            for required in required_permissions:
                if required not in actual_set:
                    missing.append(required)

            if missing:
                return AuthorizationReason(
                    source="permission",
                    outcome="deny",
                    detail=f"missing_permissions:{','.join(missing)}",
                )

            return AuthorizationReason(
                source="permission", outcome="allow", detail=None
            )

        _step.__name__ = "permission_step"
        return _step
