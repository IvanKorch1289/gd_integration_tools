"""Tests for src.backend.core.utils.cache_keys."""

from __future__ import annotations

import pytest

from src.backend.core.utils.cache_keys import build_cache_key


@pytest.mark.unit
class TestBuildCacheKey:
    """Tests for build_cache_key utility."""

    @pytest.mark.asyncio
    async def test_basic_key_generation(self) -> None:
        async def sample_func(a: int, b: str) -> str:
            return f"{a}-{b}"

        key1 = build_cache_key(sample_func, (1,), {"b": "test"})
        key2 = build_cache_key(sample_func, (1,), {"b": "test"})
        assert key1 == key2
        assert key1.startswith("cache:")

    @pytest.mark.unit
    def test_different_args_produce_different_keys(self) -> None:
        async def sample_func(a: int, b: str) -> str:
            return f"{a}-{b}"

        key1 = build_cache_key(sample_func, (1,), {"b": "test"})
        key2 = build_cache_key(sample_func, (2,), {"b": "test"})
        assert key1 != key2

    @pytest.mark.unit
    def test_different_kwargs_produce_different_keys(self) -> None:
        async def sample_func(a: int, b: str) -> str:
            return f"{a}-{b}"

        key1 = build_cache_key(sample_func, (1,), {"b": "test"})
        key2 = build_cache_key(sample_func, (1,), {"b": "other"})
        assert key1 != key2

    @pytest.mark.unit
    def test_custom_prefix(self) -> None:
        async def sample_func() -> None:
            pass

        key = build_cache_key(sample_func, (), {}, prefix="custom")
        assert key.startswith("custom:")

    @pytest.mark.unit
    def test_exclude_self_removes_first_arg(self) -> None:
        async def sample_func(self_ref: object, a: int) -> int:
            return a

        key_with_self = build_cache_key(
            sample_func, ("self", 1), {}, exclude_self=False
        )
        key_without_self = build_cache_key(
            sample_func, ("self", 1), {}, exclude_self=True
        )
        assert key_with_self != key_without_self

        # Verify exclude_self=True matches call without first arg
        key_no_first = build_cache_key(sample_func, (1,), {}, exclude_self=False)
        assert key_without_self == key_no_first

    @pytest.mark.unit
    def test_kwargs_order_independence(self) -> None:
        async def sample_func(a: int, b: str, c: float) -> None:
            pass

        key1 = build_cache_key(sample_func, (), {"a": 1, "b": "x", "c": 1.0})
        key2 = build_cache_key(sample_func, (), {"c": 1.0, "a": 1, "b": "x"})
        assert key1 == key2

    @pytest.mark.unit
    def test_different_functions_different_keys(self) -> None:
        async def func_a() -> None:
            pass

        async def func_b() -> None:
            pass

        key1 = build_cache_key(func_a, (), {})
        key2 = build_cache_key(func_b, (), {})
        assert key1 != key2
