"""Unit-тесты ResilienceProfile + InMemoryResilienceProfileStore (S13 K2 W5)."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.resilience.resilience_profile import (
    BulkheadPolicy,
    CircuitBreakerPolicy,
    RateLimitPolicy,
    ResilienceProfile,
    RetryPolicySpec,
)
from src.backend.infrastructure.resilience.profile_store_memory import (
    InMemoryResilienceProfileStore,
)


def test_profile_dataclass_default() -> None:
    p = ResilienceProfile(name="api_default")
    assert p.retry.max_attempts == 3
    assert p.circuit_breaker.failure_threshold == 5
    assert p.rate_limit is None
    assert p.bulkhead is None


def test_profile_to_dict_and_from_dict() -> None:
    p = ResilienceProfile(
        name="external_api",
        retry=RetryPolicySpec(max_attempts=5, base_delay_ms=200),
        circuit_breaker=CircuitBreakerPolicy(failure_threshold=10),
        rate_limit=RateLimitPolicy(rps=500, burst=50),
        bulkhead=BulkheadPolicy(high_watermark=200, low_watermark=100),
    )
    d = p.to_dict()
    assert d["name"] == "external_api"
    assert d["retry"]["max_attempts"] == 5
    p2 = ResilienceProfile.from_dict(d)
    assert p2 == p


def test_from_dict_partial() -> None:
    p = ResilienceProfile.from_dict({"name": "x"})
    assert p.name == "x"
    assert p.retry.max_attempts == 3
    assert p.rate_limit is None


@pytest.mark.asyncio
async def test_store_upsert_get() -> None:
    store = InMemoryResilienceProfileStore()
    p = ResilienceProfile(name="foo", retry=RetryPolicySpec(max_attempts=7))
    saved = await store.upsert(p)
    assert saved == p
    fetched = await store.get("foo")
    assert fetched == p


@pytest.mark.asyncio
async def test_store_tenant_override_falls_back_to_global() -> None:
    store = InMemoryResilienceProfileStore()
    global_p = ResilienceProfile(name="api", retry=RetryPolicySpec(max_attempts=3))
    await store.upsert(global_p)
    # Без tenant override — отдаёт global.
    fetched = await store.get("api", tenant_id="tenant-1")
    assert fetched == global_p


@pytest.mark.asyncio
async def test_store_tenant_override_returns_tenant_value() -> None:
    store = InMemoryResilienceProfileStore()
    global_p = ResilienceProfile(name="api", retry=RetryPolicySpec(max_attempts=3))
    tenant_p = ResilienceProfile(name="api", retry=RetryPolicySpec(max_attempts=10))
    await store.upsert(global_p)
    await store.upsert(tenant_p, tenant_id="tenant-1")
    fetched = await store.get("api", tenant_id="tenant-1")
    assert fetched == tenant_p
    fetched_other = await store.get("api", tenant_id="tenant-2")
    # Tenant-2 не имеет override → global.
    assert fetched_other == global_p


@pytest.mark.asyncio
async def test_store_delete() -> None:
    store = InMemoryResilienceProfileStore()
    await store.upsert(ResilienceProfile(name="bar"))
    assert await store.delete("bar") is True
    assert await store.delete("bar") is False
    assert await store.get("bar") is None


@pytest.mark.asyncio
async def test_store_list() -> None:
    store = InMemoryResilienceProfileStore()
    await store.upsert(ResilienceProfile(name="p1"))
    await store.upsert(ResilienceProfile(name="p2"))
    await store.upsert(ResilienceProfile(name="p1"), tenant_id="t1")
    profiles_global = await store.list()
    assert len(profiles_global) == 2
    profiles_t1 = await store.list(tenant_id="t1")
    names = sorted(p.name for p in profiles_t1)
    assert names == ["p1", "p2"]
