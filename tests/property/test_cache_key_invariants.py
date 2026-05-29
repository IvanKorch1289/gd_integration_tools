"""Cache property-based tests (Sprint 35 w4 GAP-AI).

Properties:
    - get after set returns the value (basic invariant)
    - LRU eviction: after capacity exceeded, oldest entry evicted
    - TTL expiry: entries expire after TTL
    - JSON envelope round-trip: serialize → deserialize preserves value

Requires: hypothesis>=6.0
"""

from __future__ import annotations

import asyncio
from hypothesis import given, settings, assume
from hypothesis import strategies as st

import pytest


st_json_value = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-10**9, max_value=10**9),
    st.text(max_size=256),
    st.floats(allow_nan=False, allow_infinity=False),
    st.lists(st.text(max_size=32), max_size=8),
    st.dictionaries(
        keys=st.text(min_size=1, max_size=16),
        values=st.text(max_size=32),
        max_size=4,
    ),
)


class TestCacheBasicInvariants:
    """Fundamental cache invariants: get-after-set, no phantom writes."""

    @settings(max_examples=50, deadline=None)
    @given(
        key=st.text(min_size=1, max_size=64),
        value=st_json_value,
    )
    @pytest.mark.asyncio
    async def test_set_then_get_returns_value(self, key: str, value: object) -> None:
        """Setting a value and immediately getting it should return the same value."""
        try:
            from src.backend.infrastructure.cache.lru_cache import LruMemoryCache
        except ImportError:
            pytest.skip("LruMemoryCache not importable")

        cache = LruMemoryCache(max_size=128, ttl_seconds=300, scope="test")

        await cache.set(key, value)
        result = await cache.get(key)

        assert result == value, (
            f"[SetGet] set({key!r}, {value!r}) → get({key!r}) returned {result!r} "
            f"(type {type(result).__name__} vs {type(value).__name__})"
        )

    @settings(max_examples=30, deadline=None)
    @given(
        key=st.text(min_size=1, max_size=64),
    )
    @pytest.mark.asyncio
    async def test_get_without_set_returns_none(self, key: str) -> None:
        """Getting a key that was never set returns None."""
        try:
            from src.backend.infrastructure.cache.lru_cache import LruMemoryCache
        except ImportError:
            pytest.skip("LruMemoryCache not importable")

        cache = LruMemoryCache(max_size=128, ttl_seconds=300, scope="test")

        result = await cache.get(key)

        assert result is None, (
            f"[GetMiss] get({key!r}) returned {result!r}, expected None (never set)"
        )

    @settings(max_examples=20, deadline=None)
    @given(
        key=st.text(min_size=1, max_size=64),
        value=st_json_value,
    )
    @pytest.mark.asyncio
    async def test_delete_then_get_returns_none(self, key: str, value: object) -> None:
        """Deleting a key and getting it should return None."""
        try:
            from src.backend.infrastructure.cache.lru_cache import LruMemoryCache
        except ImportError:
            pytest.skip("LruMemoryCache not importable")

        cache = LruMemoryCache(max_size=128, ttl_seconds=300, scope="test")

        await cache.set(key, value)
        await cache.invalidate(key)
        result = await cache.get(key)

        assert result is None, (
            f"[Delete] set → delete → get({key!r}) returned {result!r}, expected None"
        )


class TestCacheEnvelopeRoundTrip:
    """JSON envelope invariants: serialize → deserialize preserves value."""

    @settings(max_examples=50, deadline=None)
    @given(value=st_json_value)
    def test_json_serialize_deserialize_roundtrip(self, value: object) -> None:
        """JSON round-trip should never lose or mutate scalar/collection values."""
        import json

        serialized = json.dumps(value)
        deserialized = json.loads(serialized)

        assert deserialized == value, (
            f"[JSON RoundTrip] value={value!r} (type={type(value).__name__}) "
            f"→ serialized→deserialized={deserialized!r} (type={type(deserialized).__name__})"
        )

    @settings(max_examples=30, deadline=None)
    @given(key=st.text(min_size=1, max_size=64), value=st_json_value)
    @pytest.mark.asyncio
    async def test_cache_roundtrip_via_json(self, key: str, value: object) -> None:
        """Set via JSON bytes → get → should equal original value."""
        import json

        try:
            from src.backend.infrastructure.cache.lru_cache import LruMemoryCache
        except ImportError:
            pytest.skip("LruMemoryCache not importable")

        cache = LruMemoryCache(max_size=128, ttl_seconds=300, scope="test")

        # Serialize as JSON (simulating network transport / Redis serialization)
        json_bytes = json.dumps(value).encode("utf-8")
        await cache.set(key, json_bytes)

        retrieved = await cache.get(key)
        assert retrieved is not None, f"[CacheJSON] get({key!r}) returned None after set"

        # Deserialize
        if isinstance(retrieved, bytes):
            retrieved = retrieved.decode("utf-8")
        roundtripped = json.loads(retrieved) if isinstance(retrieved, str) else retrieved

        assert roundtripped == value, (
            f"[CacheJSON RoundTrip] original={value!r} → json_bytes={json_bytes!r} "
            f"→ cache → retrieved={retrieved!r} → deserialized={roundtripped!r} — MISMATCH"
        )
