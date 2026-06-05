"""Unit tests for admin_resilience_profile endpoints (S13 K2 W5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, status

from src.backend.core.resilience.resilience_profile import (
    BulkheadPolicy,
    CircuitBreakerPolicy,
    RateLimitPolicy,
    ResilienceProfile,
    RetryPolicySpec,
)
from src.backend.entrypoints.api.v1.endpoints import admin_resilience_profile as mod


@pytest.fixture
def mock_store() -> AsyncMock:
    """Returns a mocked ResilienceProfileStore."""
    return AsyncMock()


@pytest.fixture
def sample_profile() -> ResilienceProfile:
    """Returns a sample ResilienceProfile."""
    return ResilienceProfile(
        name="default",
        retry=RetryPolicySpec(max_attempts=5),
        circuit_breaker=CircuitBreakerPolicy(failure_threshold=10),
        rate_limit=RateLimitPolicy(rps=200),
        bulkhead=BulkheadPolicy(high_watermark=50),
    )


# ─── _profile_from_payload ───────────────────────────────────────────────────


def test_profile_from_payload_full() -> None:
    """_profile_from_payload builds profile from all fields."""
    payload = mod.ResilienceProfileIn(
        retry=mod.RetryPolicyIn(
            max_attempts=5,
            base_delay_ms=200,
            max_delay_ms=10000,
            exp_base=2.0,
            jitter=0.2,
        ),
        circuit_breaker=mod.CircuitBreakerIn(
            failure_threshold=10, recovery_timeout_s=60, half_open_max_calls=5
        ),
        rate_limit=mod.RateLimitIn(rps=200, burst=50),
        bulkhead=mod.BulkheadIn(high_watermark=200, low_watermark=100),
    )
    profile = mod._profile_from_payload("prod", payload)
    assert profile.name == "prod"
    assert profile.retry.max_attempts == 5
    assert profile.circuit_breaker.failure_threshold == 10
    assert profile.rate_limit is not None
    assert profile.rate_limit.rps == 200
    assert profile.bulkhead is not None
    assert profile.bulkhead.high_watermark == 200


def test_profile_from_payload_optional_none() -> None:
    """_profile_from_payload allows rate_limit and bulkhead to be None."""
    payload = mod.ResilienceProfileIn()
    profile = mod._profile_from_payload("default", payload)
    assert profile.name == "default"
    assert profile.rate_limit is None
    assert profile.bulkhead is None


# ─── list_profiles ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_profiles(
    mock_store: AsyncMock, sample_profile: ResilienceProfile
) -> None:
    """list_profiles returns serialized profiles."""
    mock_store.list.return_value = [sample_profile]

    with patch.object(mod, "get_resilience_profile_store", return_value=mock_store):
        result = await mod.list_profiles(tenant_id="t1", store=mock_store)

    assert "profiles" in result
    assert len(result["profiles"]) == 1
    assert result["profiles"][0]["name"] == "default"
    mock_store.list.assert_awaited_once_with(tenant_id="t1")


# ─── get_profile ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_profile_found(
    mock_store: AsyncMock, sample_profile: ResilienceProfile
) -> None:
    """get_profile returns profile dict when found."""
    mock_store.get.return_value = sample_profile

    with patch.object(mod, "get_resilience_profile_store", return_value=mock_store):
        result = await mod.get_profile(name="default", tenant_id=None, store=mock_store)

    assert result["name"] == "default"
    mock_store.get.assert_awaited_once_with("default", tenant_id=None)


@pytest.mark.asyncio
async def test_get_profile_not_found(mock_store: AsyncMock) -> None:
    """get_profile raises 404 when profile missing."""
    mock_store.get.return_value = None

    with patch.object(mod, "get_resilience_profile_store", return_value=mock_store):
        with pytest.raises(HTTPException) as exc_info:
            await mod.get_profile(name="missing", store=mock_store)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in exc_info.value.detail


# ─── upsert_profile ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_profile(
    mock_store: AsyncMock, sample_profile: ResilienceProfile
) -> None:
    """upsert_profile saves and returns profile dict."""
    mock_store.upsert.return_value = sample_profile

    payload = mod.ResilienceProfileIn()
    with patch.object(mod, "get_resilience_profile_store", return_value=mock_store):
        result = await mod.upsert_profile(
            name="default", payload=payload, tenant_id="t1", store=mock_store
        )

    assert result["name"] == "default"
    mock_store.upsert.assert_awaited_once()
    passed_profile = mock_store.upsert.call_args[0][0]
    assert passed_profile.name == "default"
    assert mock_store.upsert.call_args[1]["tenant_id"] == "t1"


# ─── delete_profile ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_profile(mock_store: AsyncMock) -> None:
    """delete_profile returns deleted status."""
    mock_store.delete.return_value = True

    with patch.object(mod, "get_resilience_profile_store", return_value=mock_store):
        result = await mod.delete_profile(name="old", tenant_id=None, store=mock_store)

    assert result["deleted"] is True
    mock_store.delete.assert_awaited_once_with("old", tenant_id=None)
