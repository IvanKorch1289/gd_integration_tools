from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.security.authorization_gateway.state import (
    AuthorizationReason,
    PolicyDecider,
)

_logger = get_logger("core.security.authorization_gateway")


class OpaMixin:
    """OPA (Open Policy Agent) step для AuthorizationGateway. S60 W4 extraction."""

    __slots__ = ()

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
                from src.backend.core.feature_flags import get_feature_flag_service

                if not get_feature_flag_service().is_enabled(
                    "opa_runtime_query_enabled"
                ):
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
