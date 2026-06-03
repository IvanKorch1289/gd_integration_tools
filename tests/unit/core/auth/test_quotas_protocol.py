"""Unit tests for src.backend.core.auth.quotas_protocol."""

from __future__ import annotations

from src.backend.core.auth.quotas_protocol import (
    QuotaCheckResult,
    QuotasBackend,
    QuotaUsage,
)


class FakeUsage:
    tenant_id = "t1"
    requests_in_minute = 1
    requests_in_day = 10
    cost_in_day_usd = 0.5
    reset_minute_at = 60
    reset_day_at = 86400


class FakeResult:
    allowed = True
    reason = "ok"
    usage = FakeUsage()


class FakeBackend:
    async def consume_request(self, tenant_id: str) -> FakeResult:
        return FakeResult()

    async def check_tokens(self, tenant_id: str, tokens: int) -> FakeResult:
        return FakeResult()


def test_quota_usage_isinstance() -> None:
    assert isinstance(FakeUsage(), QuotaUsage)


def test_quota_check_result_isinstance() -> None:
    assert isinstance(FakeResult(), QuotaCheckResult)


def test_quotas_backend_isinstance() -> None:
    assert isinstance(FakeBackend(), QuotasBackend)
