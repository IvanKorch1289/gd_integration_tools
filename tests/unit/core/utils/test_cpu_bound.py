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
