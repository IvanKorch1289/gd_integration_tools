"""Unit-тесты SAML → TenantContext resolver (Sprint 9 K1 W2)."""

from __future__ import annotations

import pytest

from src.backend.core.auth.saml_backend import SamlAuthResult
from src.backend.core.tenancy.saml_resolver import SamlTenantHandoff
from src.backend.core.tenancy.token_budget import (
    BudgetPeriod,
    InMemoryTokenBudgetBackend,
    TokenBudget,
    TokenBudgetConfig,
)


@pytest.fixture
def auth_result() -> SamlAuthResult:
    return SamlAuthResult(
        principal="user@bank.local",
        attributes={
            "tenant_id": "bank-corp",
            "subscription_plan": "enterprise",
            "region": "ru",
        },
        session_index="sess-1",
    )


@pytest.mark.asyncio
async def test_resolve_without_budget(auth_result: SamlAuthResult) -> None:
    handoff = SamlTenantHandoff(budget=None)
    out = await handoff.resolve(auth_result)
    assert out.tenant.tenant_id == "bank-corp"
    assert out.tenant.plan == "enterprise"
    assert out.budget_snapshot is None
    assert out.already_breached_soft is False


@pytest.mark.asyncio
async def test_resolve_with_budget(auth_result: SamlAuthResult) -> None:
    budget = TokenBudget(
        backend=InMemoryTokenBudgetBackend(),
        default_config=TokenBudgetConfig(
            soft_limit=100, hard_limit=200, period=BudgetPeriod.DAILY
        ),
    )
    await budget.reserve(tenant_id="bank-corp", tokens=150)
    handoff = SamlTenantHandoff(budget=budget)
    out = await handoff.resolve(auth_result)
    assert out.tenant.tenant_id == "bank-corp"
    assert out.budget_snapshot is not None
    assert out.budget_snapshot.used == 150
    assert out.already_breached_soft is True


@pytest.mark.asyncio
async def test_resolve_missing_tenant_id_raises() -> None:
    bad = SamlAuthResult(principal="x", attributes={"plan": "free"}, session_index=None)
    handoff = SamlTenantHandoff(budget=None)
    with pytest.raises(ValueError, match="tenant_id"):
        await handoff.resolve(bad)
