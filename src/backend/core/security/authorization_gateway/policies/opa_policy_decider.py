"""B-12 fix (cycle 37): OPA-based PolicyDecider factory.

Тонкая обёртка над :func:`AuthorizationGateway.opa_step`. Позволяет DI-провайдерам
и composition-root-у в одну строку завести OPA-проверку в :class:`AuthorizationGateway`:

>>> policies = [build_opa_policy_decider(opa_client)]
>>> AuthorizationGateway(..., policies=policies)

Слой ``core`` не импортирует ``infrastructure`` напрямую — OPA-клиент передаётся
через ``Any`` (duck-type: ``async query(policy, input) -> Decision``).
Контракт проверяется тестами в ``tests/integration/test_opa_runtime_cycle37.py``.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.security.authorization_gateway import AuthorizationGateway
from src.backend.core.security.authorization_gateway.state import PolicyDecider

__all__ = ("OPAPolicyDecider", "build_opa_policy_decider")


def build_opa_policy_decider(
    opa_client: Any,
    *,
    policy_name: str = "authz/default",
) -> PolicyDecider:
    """Создать :data:`PolicyDecider` из OPA-клиента (B-12 fix, cycle 37).

    Args:
        opa_client: OPA-клиент (duck-type ``async query(policy, input) -> Decision``
            с атрибутами ``allow: bool`` и ``reasons: list[str]``). Обычно это
            ``src.backend.infrastructure.policy.opa.client.OPAClient``, но
            допускается любой тестовый stub.
        policy_name: Имя rego-package (точки → слэши на стороне клиента),
            например ``"authz/default"``.

    Returns:
        :data:`PolicyDecider` callable, ready-to-use в
        ``AuthorizationGateway(..., policies=(...,))``.
    """
    # B-12 fix (cycle 37): composition root delegating к existing фабрике
    # для избежания рассинхрона с feature-flag/deny-by-default
    # поведением ``opa_step``.
    return AuthorizationGateway.opa_step(opa_client, policy_name)


# Краткий alias для DI — запись короче.
OPAPolicyDecider = build_opa_policy_decider
