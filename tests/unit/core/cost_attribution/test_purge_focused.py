"""Tests for ``CostAttribution.purge_older_than()`` (Sprint 175+ P1.2)."""

from __future__ import annotations

import time

import pytest

from src.backend.core.cost_attribution import (
    CostAttribution,
    ResourceType,
    get_cost_registry,
)
from src.backend.core.cost_attribution.attribution import (
    reset_cost_attribution,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_cost_attribution()
    get_cost_registry().clear()
    yield
    reset_cost_attribution()
    get_cost_registry().clear()


class TestPurgeOlderThanBasic:
    def test_purge_no_records(self) -> None:
        ca = CostAttribution()
        removed = ca.purge_older_than(seconds=60)
        assert removed == 0

    def test_purge_removes_old_records(self) -> None:
        ca = CostAttribution()
        ca.record(
            tenant_id="t1", route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100, cost_usd=0.01,
        )
        # Manually set timestamp to past.
        ca._records[-1].timestamp = time.time() - 120
        ca.record(
            tenant_id="t1", route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100, cost_usd=0.01,
        )
        # New record has current timestamp.
        removed = ca.purge_older_than(seconds=60)
        assert removed == 1
        assert ca.size() == 1

    def test_purge_keeps_recent(self) -> None:
        ca = CostAttribution()
        ca.record(
            tenant_id="t1", route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100, cost_usd=0.01,
        )
        removed = ca.purge_older_than(seconds=60)
        assert removed == 0
        assert ca.size() == 1

    def test_purge_all_old(self) -> None:
        ca = CostAttribution()
        for _ in range(3):
            ca.record(
                tenant_id="t1", route_id="r1",
                resource_type=ResourceType.LLM_TOKENS,
                units=100, cost_usd=0.01,
            )
        # All records are "old".
        old_time = time.time() - 1000
        for r in ca._records:
            r.timestamp = old_time
        removed = ca.purge_older_than(seconds=60)
        assert removed == 3
        assert ca.size() == 0

    def test_purge_mixed(self) -> None:
        ca = CostAttribution()
        # 2 old + 3 new.
        for _ in range(2):
            ca.record(
                tenant_id="t1", route_id="r1",
                resource_type=ResourceType.LLM_TOKENS,
                units=100, cost_usd=0.01,
            )
        # Mark first 2 as old.
        for r in ca._records[:2]:
            r.timestamp = time.time() - 120
        for _ in range(3):
            ca.record(
                tenant_id="t1", route_id="r1",
                resource_type=ResourceType.LLM_TOKENS,
                units=100, cost_usd=0.01,
            )
        removed = ca.purge_older_than(seconds=60)
        assert removed == 2
        assert ca.size() == 3

    def test_purge_custom_now(self) -> None:
        ca = CostAttribution()
        # Two records with known timestamps.
        for ts in [1000.0, 1000.0]:
            ca.record(
                tenant_id="t1", route_id="r1",
                resource_type=ResourceType.LLM_TOKENS,
                units=100, cost_usd=0.01,
            )
            ca._records[-1].timestamp = ts
        # now=1100.0, seconds=60. threshold = 1100 - 60 = 1040.
        # Both records timestamp 1000 < 1040, so OLD.
        removed = ca.purge_older_than(seconds=60, now=1100.0)
        assert removed == 2
        ca._records.clear()
        # Two more records.
        for ts in [1000.0, 1000.0]:
            ca.record(
                tenant_id="t1", route_id="r1",
                resource_type=ResourceType.LLM_TOKENS,
                units=100, cost_usd=0.01,
            )
            ca._records[-1].timestamp = ts
        # now=1050.0, seconds=60. threshold = 1050 - 60 = 990.
        # Both records timestamp 1000 >= 990, so KEPT.
        removed = ca.purge_older_than(seconds=60, now=1050.0)
        assert removed == 0


class TestPurgeEdgeCases:
    def test_purge_zero_seconds(self) -> None:
        """seconds=0 → purge records with timestamp < now (effectively all)."""
        ca = CostAttribution()
        ca.record(
            tenant_id="t1", route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100, cost_usd=0.01,
        )
        # Record with timestamp slightly in past.
        ca._records[-1].timestamp = time.time() - 0.1
        removed = ca.purge_older_than(seconds=0)
        assert removed == 1

    def test_purge_negative_seconds(self) -> None:
        """seconds=-1 → purge all records older than now + 1 (always)."""
        ca = CostAttribution()
        ca.record(
            tenant_id="t1", route_id="r1",
            resource_type=ResourceType.LLM_TOKENS,
            units=100, cost_usd=0.01,
        )
        # All records are "in past" relative to now+1.
        removed = ca.purge_older_than(seconds=-1)
        assert removed == 1

    def test_purge_returns_count(self) -> None:
        ca = CostAttribution()
        for _ in range(5):
            ca.record(
                tenant_id="t1", route_id="r1",
                resource_type=ResourceType.LLM_TOKENS,
                units=100, cost_usd=0.01,
            )
        for r in ca._records:
            r.timestamp = time.time() - 100
        # All 5 should be purged.
        n = ca.purge_older_than(seconds=60)
        assert n == 5
        assert ca.size() == 0
