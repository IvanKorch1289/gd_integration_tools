"""SAML → TenantContext resolver (Sprint 9 K1 W2).

Преобразует :class:`SamlAuthResult` в :class:`TenantContext`
+ автоматически вызывает :class:`TokenBudget.snapshot` для пред-проверки
лимитов перед обработкой первого запроса.

Используется ACS-endpoint (см.
:mod:`entrypoints.api.v1.endpoints.auth_saml`) и контекстная middleware
для уже-аутентифицированных запросов с saml_session cookie.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.backend.core.auth.saml_backend import SamlAuthResult
from src.backend.core.tenancy import TenantContext
from src.backend.core.tenancy.budget_enforcer import tenant_from_saml_attributes
from src.backend.core.tenancy.token_budget import BudgetSnapshot, TokenBudget

__all__ = ("SamlTenantHandoff", "SamlTenantResolveResult")


@dataclass(frozen=True, slots=True)
class SamlTenantResolveResult:
    """Результат resolve операции.

    Attributes:
        tenant: :class:`TenantContext` из SAML атрибутов.
        budget_snapshot: текущее состояние бюджета (или None если бюджет
            не настроен / fail-open).
        already_breached_soft: ``True`` если на момент логина soft уже
            пробит — caller может показать предупреждение.
    """

    tenant: TenantContext
    budget_snapshot: BudgetSnapshot | None
    already_breached_soft: bool


class SamlTenantHandoff:
    """Преобразует SAML-результат в :class:`TenantContext` + snapshot бюджета.

    Args:
        budget: опц. :class:`TokenBudget` для пред-проверки;
            если None — handoff просто создаёт TenantContext.
    """

    def __init__(self, *, budget: TokenBudget | None = None) -> None:
        self._budget = budget

    async def resolve(
        self, auth_result: SamlAuthResult
    ) -> SamlTenantResolveResult:
        """Построить TenantContext + (опц.) snapshot бюджета."""
        tenant = tenant_from_saml_attributes(attributes=auth_result.attributes)
        if self._budget is None:
            return SamlTenantResolveResult(
                tenant=tenant,
                budget_snapshot=None,
                already_breached_soft=False,
            )
        snapshot = await self._budget.snapshot(tenant_id=tenant.tenant_id)
        return SamlTenantResolveResult(
            tenant=tenant,
            budget_snapshot=snapshot,
            already_breached_soft=snapshot.soft_breached,
        )
