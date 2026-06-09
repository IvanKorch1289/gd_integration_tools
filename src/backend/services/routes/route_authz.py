"""K3 S19 W3: Route-level authorization via AuthorizationGateway.

Обеспечивает проверку ``requires_permission`` из ``route.toml [security]``
перед dispatch на route через :class:`AuthorizationGateway`.

Использование::

    from src.backend.services.routes.route_authz import check_route_permission

    # Внутри entrypoint перед вызовом route:
    allowed, reason = await check_route_permission(
        route_id="my_route",
        principal="user-123",
        permissions=("role:admin", "scope:credit.read"),
    )
    if not allowed:
        raise PermissionDenied(reason)
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.security.authorization_gateway import AuthorizationGateway

__all__ = ("check_route_permission",)

_logger = get_logger("services.routes.route_authz")


async def check_route_permission(
    *,
    route_id: str,
    principal: str,
    permissions: tuple[str, ...],
    context: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Проверяет permission для route через AuthorizationGateway.

    Args:
        route_id: Идентификатор маршрута (для логирования).
        principal: Идентификатор principal (user / plugin).
        permissions: Кортеж required permissions из ``route.toml [security]
            requires_permission``.
        context: Дополнительный контекст для AuthorizationGateway.

    Returns:
        tuple[bool, str]: (allowed, reason). Если allowed=True — доступ разрешён.
        Если allowed=False — reason содержит описание почему.

    Raises:
        RuntimeError: Если AuthorizationGateway недоступен (fail-closed).
    """
    if not permissions:
        return True, "no_permissions_required"

    ctx = dict(context or {})
    ctx["route_id"] = route_id

    try:
        gateway = _resolve_authz_gateway()
    except Exception as exc:
        _logger.error("route_authz_gateway_unavailable: %s", exc)
        raise RuntimeError(
            f"AuthorizationGateway unavailable for route {route_id}: {exc}"
        ) from exc

    if gateway is None:
        _logger.warning(
            "route_authz_gateway_not_registered route_id=%s principal=%s",
            route_id,
            principal,
        )
        # Gateway not registered — fail-closed для security
        return False, "authorization_gateway_not_registered"

    # Build permission_step policy
    permission_policy = AuthorizationGateway.permission_step(permissions)

    # Create temporary gateway with permission policy only
    # (capability check is done separately by the caller if needed)
    temp_gateway = AuthorizationGateway(
        capability_gateway=gateway._capability_gateway,
        policies=(permission_policy,),
        enabled=True,
    )

    try:
        decision = await temp_gateway.authorize(
            principal=principal,
            resource=f"route:{route_id}",
            action="execute",
            context=ctx,
        )
    except Exception as exc:
        _logger.error(
            "route_authz_check_failed route_id=%s principal=%s error=%s",
            route_id,
            principal,
            exc,
        )
        return False, f"authorization_check_error:{exc}"

    if decision.allowed:
        return True, "allowed"

    # Extract deny reason
    deny_reasons = [
        f"{r.source}:{r.detail}" for r in decision.reasons if r.outcome != "allow"
    ]
    reason = "; ".join(deny_reasons) if deny_reasons else "permission_denied"
    return False, reason


def _resolve_authz_gateway() -> AuthorizationGateway | None:
    """Lazy resolve AuthorizationGateway через ai_agent service.

    Returns:
        AuthorizationGateway instance или None если не зарегистрирован.
    """
    # Pattern from ai_agent.py::_resolve_authz_gateway
    try:
        from src.backend.services.ai.ai_agent import get_ai_agent_service

        agent = get_ai_agent_service()
        gateway = getattr(agent, "_authz_gateway", None)
        if gateway is not None:
            return gateway
    except Exception:
        _logger.debug("route_authz_gateway_resolve_failed", exc_info=True)
        # Graceful degradation — caller handles None via fail-closed
        pass

    return None
