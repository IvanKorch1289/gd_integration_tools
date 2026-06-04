"""Unit-тесты TokenBudget + BudgetEnforcer (Sprint 9 K4 W1)."""

from __future__ import annotations

import pytest

from src.backend.core.tenancy.budget_enforcer import (
    enforce_pre_call,
    enforce_post_call,
    render_429,
    tenant_from_saml_attributes,
)
from src.backend.core.tenancy.token_budget import (
    BudgetExceeded,
    BudgetPeriod,
    InMemoryTokenBudgetBackend,
    TokenBudget,
    TokenBudgetConfig,
)


@pytest.fixture
def budget() -> TokenBudget:
    return TokenBudget(
        backend=InMemoryTokenBudgetBackend(),
        default_config=TokenBudgetConfig(
            soft_limit=100, hard_limit=200, period=BudgetPeriod.DAILY
        ),
    )


@pytest.mark.asyncio
async def test_reserve_within_limits(budget: TokenBudget) -> None:
    snapshot = await budget.reserve(tenant_id="t-1", tokens=50)
    assert snapshot.used == 50
    assert not snapshot.soft_breached
    assert not snapshot.hard_breached
    assert snapshot.remaining == 150


@pytest.mark.asyncio
async def test_reserve_soft_breached(budget: TokenBudget) -> None:
    snapshot = await budget.reserve(tenant_id="t-2", tokens=120)
    assert snapshot.soft_breached
    assert not snapshot.hard_breached


@pytest.mark.asyncio
async def test_reserve_hard_breached_raises(budget: TokenBudget) -> None:
    with pytest.raises(BudgetExceeded) as ctx:
        await budget.reserve(tenant_id="t-3", tokens=300)
    assert ctx.value.tenant_id == "t-3"
    assert ctx.value.used == 300
    assert ctx.value.hard_limit == 200


@pytest.mark.asyncio
async def test_snapshot_does_not_increment(budget: TokenBudget) -> None:
    await budget.reserve(tenant_id="t-4", tokens=42)
    snap1 = await budget.snapshot(tenant_id="t-4")
    snap2 = await budget.snapshot(tenant_id="t-4")
    assert snap1.used == 42
    assert snap2.used == 42


@pytest.mark.asyncio
async def test_reset_clears_counter(budget: TokenBudget) -> None:
    await budget.reserve(tenant_id="t-5", tokens=80)
    await budget.reset(tenant_id="t-5")
    snap = await budget.snapshot(tenant_id="t-5")
    assert snap.used == 0


@pytest.mark.asyncio
async def test_enforce_pre_call_within(budget: TokenBudget) -> None:
    snap = await enforce_pre_call(budget=budget, tenant_id="t-pre", estimated_tokens=50)
    assert snap.used == 50


@pytest.mark.asyncio
async def test_enforce_post_call_diff_positive(budget: TokenBudget) -> None:
    await enforce_pre_call(budget=budget, tenant_id="t-post", estimated_tokens=40)
    snap = await enforce_post_call(
        budget=budget, tenant_id="t-post", estimated_tokens=40, actual_tokens=80
    )
    assert snap is not None
    assert snap.used == 80


@pytest.mark.asyncio
async def test_enforce_post_call_diff_zero_or_negative(budget: TokenBudget) -> None:
    await enforce_pre_call(budget=budget, tenant_id="t-post-2", estimated_tokens=60)
    snap = await enforce_post_call(
        budget=budget, tenant_id="t-post-2", estimated_tokens=60, actual_tokens=40
    )
    assert snap is not None
    assert snap.used == 60


def test_render_429_shape() -> None:
    exc = BudgetExceeded(
        tenant_id="t", used=999, hard_limit=200, period=BudgetPeriod.DAILY
    )
    body = render_429(exc)
    assert body["error"] == "token_budget_exceeded"
    assert body["tenant_id"] == "t"
    assert body["used_tokens"] == 999
    assert body["hard_limit"] == 200
    assert body["period"] == BudgetPeriod.DAILY


def test_tenant_from_saml_attributes_basic() -> None:
    ctx = tenant_from_saml_attributes(
        attributes={
            "tenant_id": "bank-corp",
            "subscription_plan": "enterprise",
            "region": "eu",
        }
    )
    assert ctx.tenant_id == "bank-corp"
    assert ctx.plan == "enterprise"
    assert ctx.region == "eu"


def test_tenant_from_saml_attributes_array_values() -> None:
    ctx = tenant_from_saml_attributes(
        attributes={"tenant_id": ["bank-corp"], "subscription_plan": ["pro"]}
    )
    assert ctx.tenant_id == "bank-corp"
    assert ctx.plan == "pro"
    assert ctx.region == "ru"


def test_tenant_from_saml_attributes_missing_tenant_raises() -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        tenant_from_saml_attributes(attributes={"foo": "bar"})


def test_tenant_from_saml_attributes_default_plan_region() -> None:
    ctx = tenant_from_saml_attributes(attributes={"tenant_id": "x"})
    assert ctx.plan == "free"
    assert ctx.region == "ru"


@pytest.mark.asyncio
async def test_fail_open_on_backend_error() -> None:
    class _FlakyBackend:
        async def increment(self, **_: object) -> int:
            raise ConnectionError("redis down")

        async def get(self, **_: object) -> int:
            return 0

        async def reset(self, **_: object) -> None:
            return None

    budget_open = TokenBudget(
        backend=_FlakyBackend(),
        default_config=TokenBudgetConfig(
            soft_limit=10, hard_limit=20, fail_mode="open"
        ),
    )
    snap = await budget_open.reserve(tenant_id="t-fail-open", tokens=100)
    assert snap.used == 0  # fail-open → counter не учтён


@pytest.mark.asyncio
async def test_fail_closed_on_backend_error() -> None:
    class _FlakyBackend:
        async def increment(self, **_: object) -> int:
            raise ConnectionError("redis down")

        async def get(self, **_: object) -> int:
            return 0

        async def reset(self, **_: object) -> None:
            return None

    budget_closed = TokenBudget(
        backend=_FlakyBackend(),
        default_config=TokenBudgetConfig(
            soft_limit=10, hard_limit=20, fail_mode="closed"
        ),
    )
    with pytest.raises(ConnectionError):
        await budget_closed.reserve(tenant_id="t-fail-closed", tokens=5)
