"""Budget enforcer (Sprint 9 K4 W1 + K1 W2).

High-level decorator/middleware для интеграции :class:`TokenBudget` с
LiteLLM gateway:

* :func:`enforce_pre_call` — резервирует estimated tokens ДО LLM-вызова;
* :func:`enforce_post_call` — корректирует фактическим usage'ом из ответа;
* :func:`render_429` — стандартный JSON для 429 ответа.

SAML handoff (K1 W2): :func:`tenant_from_saml_attributes` — резолвер
TenantContext из SAML атрибутов.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.backend.core.tenancy import TenantContext
from src.backend.core.tenancy.token_budget import (
    BudgetExceeded,
    BudgetSnapshot,
    TokenBudget,
)

__all__ = (
    "enforce_pre_call",
    "enforce_post_call",
    "render_429",
    "tenant_from_saml_attributes",
)


async def enforce_pre_call(
    *, budget: TokenBudget, tenant_id: str, estimated_tokens: int
) -> BudgetSnapshot:
    """Резервирует estimated_tokens.

    Raises:
        BudgetExceeded: если hard_limit превышен.
    """
    return await budget.reserve(tenant_id=tenant_id, tokens=estimated_tokens)


async def enforce_post_call(
    *, budget: TokenBudget, tenant_id: str, estimated_tokens: int, actual_tokens: int
) -> BudgetSnapshot | None:
    """Корректирует разницу между estimated и actual после ответа LLM.

    Если actual < estimated — refund отсутствует (overhead принимаем).
    Если actual > estimated — дополнительный reserve.
    """
    diff = actual_tokens - estimated_tokens
    if diff <= 0:
        return await budget.snapshot(tenant_id=tenant_id)
    return await budget.reserve(tenant_id=tenant_id, tokens=diff)


def render_429(exc: BudgetExceeded) -> dict[str, Any]:
    """Сформировать стандартный JSON для 429.

    Используется LLM gateway + invocation endpoints.
    """
    return {
        "error": "token_budget_exceeded",
        "tenant_id": exc.tenant_id,
        "used_tokens": exc.used,
        "hard_limit": exc.hard_limit,
        "period": exc.period,
        "message": str(exc),
    }


# --- SAML handoff (K1 W2) ---

_SAML_TENANT_ATTR = "tenant_id"
_SAML_PLAN_ATTR = "subscription_plan"
_SAML_REGION_ATTR = "region"


def tenant_from_saml_attributes(
    *,
    attributes: Mapping[str, Any],
    default_plan: str = "free",
    default_region: str = "ru",
) -> TenantContext:
    """Построить :class:`TenantContext` из SAML атрибутов.

    Ожидаемые атрибуты:

    * ``tenant_id`` — обязательный.
    * ``subscription_plan`` — опциональный, default ``free``.
    * ``region`` — опциональный, default ``ru``.

    Если атрибут — массив (типично для SAML), берём первый элемент.

    Raises:
        ValueError: если ``tenant_id`` отсутствует.
    """

    def _unwrap(val: Any) -> str | None:
        if val is None:
            return None
        if isinstance(val, (list, tuple)) and val:
            return str(val[0])
        return str(val) if val else None

    tenant_id = _unwrap(attributes.get(_SAML_TENANT_ATTR))
    if not tenant_id:
        raise ValueError(
            f"SAML attribute {_SAML_TENANT_ATTR!r} required for TenantContext"
        )
    plan = _unwrap(attributes.get(_SAML_PLAN_ATTR)) or default_plan
    region = _unwrap(attributes.get(_SAML_REGION_ATTR)) or default_region
    return TenantContext(tenant_id=tenant_id, plan=plan, region=region)
