"""Tests for run_cpu_bound (S171 M6 — performance helper)."""
from __future__ import annotations
import asyncio

import pytest


class TestRunCpuBound:
    @pytest.mark.asyncio
    async def test_thread_pool_default(self) -> None:
        """Default mode = asyncio.to_thread."""
        from src.backend.core.utils.cpu_bound import run_cpu_bound
        result = await run_cpu_bound(sum, [1, 2, 3, 4, 5])
        assert result == 15

    @pytest.mark.asyncio
    async def test_process_pool_explicit(self) -> None:
        """Explicit use_process_pool=True → ProcessPoolExecutor."""
        from src.backend.core.utils.cpu_bound import run_cpu_bound
        result = await run_cpu_bound(sum, [10, 20, 30], use_process_pool=True)
        assert result == 60

    @pytest.mark.asyncio
    async def test_kwargs_passed(self) -> None:
        from src.backend.core.utils.cpu_bound import run_cpu_bound
        result = await run_cpu_bound(pow, 2, exp=3)
        assert result == 8

    def test_pool_size_default(self) -> None:
        from src.backend.core.utils.cpu_bound import PROCESS_POOL_SIZE
        assert PROCESS_POOL_SIZE >= 1

    def test_default_cpu_pool_singleton(self) -> None:
        from src.backend.core.utils.cpu_bound import default_cpu_pool
        p1 = default_cpu_pool()
        p2 = default_cpu_pool()
        assert p1 is p2  # singleton


class TestPickleFallback:
    @pytest.mark.asyncio
    async def test_lambda_falls_back_to_thread(self) -> None:
        """use_process_pool=True with lambda → fallback to asyncio.to_thread."""
        from src.backend.core.utils.cpu_bound import run_cpu_bound
        # Lambda is NOT picklable
        result = await run_cpu_bound(lambda x: x * 2, 21, use_process_pool=True)
        assert result == 42

    @pytest.mark.asyncio
    async def test_closure_falls_back_to_thread(self) -> None:
        """Closure с nonlocal state → fallback to thread."""
        from src.backend.core.utils.cpu_bound import run_cpu_bound
        multiplier = 3

        def closure(x: int) -> int:
            return x * multiplier

        result = await run_cpu_bound(closure, 14, use_process_pool=True)
        assert result == 42

    @pytest.mark.asyncio
    async def test_picklable_top_level_uses_process_pool(self) -> None:
        """Top-level function → process pool works."""
        from src.backend.core.utils.cpu_bound import run_cpu_bound

        def top_level_fn(x: int) -> int:
            return x + 1

        result = await run_cpu_bound(top_level_fn, 41, use_process_pool=True)
        assert result == 42
