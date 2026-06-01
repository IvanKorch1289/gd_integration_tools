"""Тесты admin cache metrics endpoint (CACHE-3).

Tests verify the /cache/stats endpoint behavior by calling the underlying
function directly. The full admin router is NOT used because it is a
module-level singleton with complex dependencies (Oracle DB config, etc.)
that are not available in the test environment.

The endpoint function `_get_cache_stats` itself is pure and does not
require Redis — it aggregates metrics from in-memory counters.
"""
from __future__ import annotations

import pytest

from src.backend.entrypoints.api.v1.endpoints.admin import _get_cache_stats


@pytest.mark.anyio
class TestCacheStatsEndpoint:
    """Direct unit tests for the cache stats endpoint function."""

    async def test_cache_stats_returns_all_required_fields(self) -> None:
        """Endpoint returns all required metric fields from all cache tiers."""
        result = await _get_cache_stats()
        assert isinstance(result, dict)
        assert "lru_cache_hits" in result
        assert "lru_cache_misses" in result
        assert "rag_hits" in result
        assert "rag_misses" in result
        assert "semantic_tier_hits" in result
        assert "total_lru_hits" in result
        assert "total_lru_misses" in result
        assert "total_rag_hits" in result
        assert "total_rag_misses" in result

    async def test_cache_stats_rag_hits_has_tier_structure(self) -> None:
        """RAG hits include l1/l2/l3 tier breakdown."""
        result = await _get_cache_stats()
        rag_hits = result["rag_hits"]
        assert isinstance(rag_hits, dict)
        for tier in ("l1", "l2", "l3"):
            assert tier in rag_hits, f"Missing tier {tier} in rag_hits"
            assert isinstance(rag_hits[tier], int), f"rag_hits[{tier}] must be int"

    async def test_cache_stats_rag_misses_has_tier_structure(self) -> None:
        """RAG misses include l1/l2/l3 tier breakdown."""
        result = await _get_cache_stats()
        rag_misses = result["rag_misses"]
        assert isinstance(rag_misses, dict)
        for tier in ("l1", "l2", "l3"):
            assert tier in rag_misses, f"Missing tier {tier} in rag_misses"
            assert isinstance(rag_misses[tier], int), f"rag_misses[{tier}] must be int"

    async def test_cache_stats_all_values_are_non_negative_integers(self) -> None:
        """All metric values are non-negative integers (from in-memory counters)."""
        result = await _get_cache_stats()
        int_fields = [
            "lru_cache_hits",
            "lru_cache_misses",
            "semantic_tier_hits",
            "total_lru_hits",
            "total_lru_misses",
            "total_rag_hits",
            "total_rag_misses",
        ]
        for field in int_fields:
            assert field in result
            assert isinstance(result[field], int), f"{field} must be int"
            assert result[field] >= 0, f"{field} must be non-negative"

    async def test_cache_stats_totals_match_component_values(self) -> None:
        """total_rag_hits == sum of all rag_hits tiers."""
        result = await _get_cache_stats()
        expected_total = sum(result["rag_hits"].values())
        assert result["total_rag_hits"] == expected_total

    async def test_cache_stats_semantic_tier_equals_l3_hits(self) -> None:
        """semantic_tier_hits equals rag_hits['l3'] (L3 is the semantic tier)."""
        result = await _get_cache_stats()
        assert result["semantic_tier_hits"] == result["rag_hits"]["l3"]

    async def test_cache_stats_endpoint_returns_metrics(self) -> None:
        """Test that the cache stats endpoint returns metrics from all tiers."""
        result = await _get_cache_stats()
        # Verify all expected fields are present
        assert "lru_cache_hits" in result
        assert "lru_cache_misses" in result
        assert "rag_hits" in result
        assert "rag_misses" in result
        assert "semantic_tier_hits" in result
        # Verify all values are non-negative integers
        assert isinstance(result["lru_cache_hits"], int)
        assert isinstance(result["lru_cache_misses"], int)
        assert isinstance(result["semantic_tier_hits"], int)
        assert result["lru_cache_hits"] >= 0
        assert result["lru_cache_misses"] >= 0
        assert result["semantic_tier_hits"] >= 0
        # Verify RAG metrics have tier structure
        assert isinstance(result["rag_hits"], dict)
        assert isinstance(result["rag_misses"], dict)
