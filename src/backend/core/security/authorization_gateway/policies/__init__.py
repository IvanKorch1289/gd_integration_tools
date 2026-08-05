"""B-12 fix (cycle 37): policy-decider factories для composition root.

Здесь живут тонкие обёртки над :class:`AuthorizationGateway.opa_step` и
:func:`AuthorizationGateway.casbin_step`, чтобы DI-провайдеры могли
подключать runtime policy-движки без ссылки на mixin-методы класса.

Пример::

    from src.backend.core.security.authorization_gateway.policies import (
        build_opa_policy_decider,
    )

    policies = [build_opa_policy_decider(opa_client)]
    gateway = AuthorizationGateway(..., policies=policies)

Слой ``core`` хранит **только сигнатуры фабрик** — конкретные
инстансы (``OPAClient``, ``TenantScopedCasbin``) поднимаются в
``plugins/composition/di.py`` (composition root) из
``src/backend/infrastructure/policy/``.
"""

from __future__ import annotations

from src.backend.core.security.authorization_gateway.policies.casbin_policy_decider import (
    CasbinPolicyDecider,
    build_casbin_policy_decider,
)
from src.backend.core.security.authorization_gateway.policies.opa_policy_decider import (
    OPAPolicyDecider,
    build_opa_policy_decider,
)

__all__ = (
    "OPAPolicyDecider",
    "CasbinPolicyDecider",
    "build_opa_policy_decider",
    "build_casbin_policy_decider",
)
