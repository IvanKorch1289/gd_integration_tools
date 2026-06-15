from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.security.authorization_gateway.state import (
    AuthorizationReason,
    PolicyDecider,
)

_logger = get_logger("core.security.authorization_gateway")


class PermissionMixin:
    """permission step (custom logic) для AuthorizationGateway. S60 W4 extraction."""

    __slots__ = ()

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
                from src.backend.core.feature_flags import get_feature_flag_service

                if not get_feature_flag_service().is_enabled(
                    "route_authz_requires_permission"
                ):
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
