"""Sprint 7 K1 — unit-тесты QuotasService.

Покрывает:
    1. Default-OFF: при выключенном feature_flag все consume_* allowed.
    2. consume_request с лимитом rpm — отказ при превышении.
    3. consume_request с лимитом rpd — отказ при превышении.
    4. check_tokens отказывает при превышении max_tokens_per_request.
    5. consume_cost — отказ при превышении cost_budget_usd.
    6. window_for возвращает per-tenant override.
"""

from __future__ import annotations

import pytest

from src.backend.services.billing.quotas_service import QuotasService, QuotaWindow


@pytest.fixture
def enable_billing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включает feature_flag per_tenant_billing_enabled=True."""
    from src.backend.core.config import features as features_mod

    class _FlagsStub:
        per_tenant_billing_enabled = True

    monkeypatch.setattr(features_mod, "feature_flags", _FlagsStub())


@pytest.fixture
def disable_billing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Гарантирует per_tenant_billing_enabled=False."""
    from src.backend.core.config import features as features_mod

    class _FlagsStub:
        per_tenant_billing_enabled = False

    monkeypatch.setattr(features_mod, "feature_flags", _FlagsStub())


@pytest.mark.asyncio
async def test_consume_request_default_off_returns_allowed(
    disable_billing: None,
) -> None:
    """При выключенном feature_flag consume_request возвращает allowed=True."""
    service = QuotasService(default_window=QuotaWindow(max_rpm=1))
    result = await service.consume_request("acme")
    assert result.allowed is True
    assert result.usage.requests_in_minute == 0


@pytest.mark.asyncio
async def test_consume_request_denies_when_rpm_exceeded(enable_billing: None) -> None:
    """consume_request отказывает при превышении rpm."""
    service = QuotasService(default_window=QuotaWindow(max_rpm=2))
    r1 = await service.consume_request("acme")
    r2 = await service.consume_request("acme")
    r3 = await service.consume_request("acme")
    assert r1.allowed is True
    assert r2.allowed is True
    assert r3.allowed is False
    assert "rpm exceeded" in r3.reason


@pytest.mark.asyncio
async def test_consume_request_denies_when_rpd_exceeded(enable_billing: None) -> None:
    """consume_request отказывает при превышении rpd."""
    service = QuotasService(default_window=QuotaWindow(max_rpm=100, max_rpd=1))
    r1 = await service.consume_request("acme")
    r2 = await service.consume_request("acme")
    assert r1.allowed is True
    assert r2.allowed is False
    assert "rpd exceeded" in r2.reason


@pytest.mark.asyncio
async def test_check_tokens_denies_when_request_exceeds_limit(
    enable_billing: None,
) -> None:
    """check_tokens отказывает при tokens > max_tokens_per_request."""
    service = QuotasService(default_window=QuotaWindow(max_tokens_per_request=1000))
    ok = await service.check_tokens("acme", 500)
    fail = await service.check_tokens("acme", 1500)
    assert ok.allowed is True
    assert fail.allowed is False
    assert "tokens_per_request" in fail.reason


@pytest.mark.asyncio
async def test_consume_cost_denies_when_budget_exceeded(enable_billing: None) -> None:
    """consume_cost отказывает при превышении дневного USD-бюджета."""
    service = QuotasService(default_window=QuotaWindow(cost_budget_usd=1.0))
    r1 = await service.consume_cost("acme", 0.5)
    r2 = await service.consume_cost("acme", 0.4)
    r3 = await service.consume_cost("acme", 0.2)
    assert r1.allowed is True
    assert r2.allowed is True
    assert r3.allowed is False
    assert "cost_budget_usd" in r3.reason


def test_window_for_returns_per_tenant_override() -> None:
    """window_for возвращает override для известного tenant_id."""
    custom = QuotaWindow(max_rpm=999, max_rpd=99, cost_budget_usd=10.0)
    service = QuotasService(
        default_window=QuotaWindow(max_rpm=10), per_tenant_windows={"vip": custom}
    )
    assert service.window_for("vip") == custom
    assert service.window_for("regular").max_rpm == 10


@pytest.mark.asyncio
async def test_usage_snapshot_reflects_counters(enable_billing: None) -> None:
    """usage_snapshot возвращает накопленные значения rpm/rpd/cost."""
    service = QuotasService(
        default_window=QuotaWindow(max_rpm=100, max_rpd=100, cost_budget_usd=10.0)
    )
    await service.consume_request("acme")
    await service.consume_request("acme")
    await service.consume_cost("acme", 0.25)
    snap = await service.usage_snapshot("acme")
    assert snap.tenant_id == "acme"
    assert snap.requests_in_minute >= 2
    assert snap.requests_in_day >= 2
    assert pytest.approx(snap.cost_in_day_usd, rel=1e-3) == 0.25
