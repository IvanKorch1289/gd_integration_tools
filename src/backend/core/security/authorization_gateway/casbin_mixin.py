from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


from src.backend.core.logging import get_logger

_logger = get_logger("core.security.authorization_gateway")


class CasbinMixin:
    """Casbin authorization step для AuthorizationGateway. S60 W4 extraction."""

    __slots__ = ()

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
