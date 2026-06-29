"""TDD: AsyncUtils (S171 M27+, D291)."""
# ruff: noqa: S101
from __future__ import annotations
import asyncio
import pytest


class TestAsyncUtils:
    def test_gather_with_timeout(self) -> None:
        from src.backend.core.utils.async_utils import gather_with_timeout
        results = []
        async def collect():
            async for r in gather_with_timeout(
                [asyncio.sleep(0.01, result=42), asyncio.sleep(0.01, result=99)],
                timeout=1.0,
            ):
                results.append(r)
        asyncio.run(collect())
        assert 42 in results
        assert 99 in results

    def test_safe_gather_logs_errors(self) -> None:
        from src.backend.core.utils.async_utils import safe_gather

        async def failer():
            raise ValueError("test")

        async def main():
            return await safe_gather([asyncio.sleep(0.01, result=1), failer()])
        results = asyncio.run(main())
        assert results[0] == 1
        assert isinstance(results[1], ValueError)

    def test_run_sync_in_thread_signature(self) -> None:
        from src.backend.core.utils.async_utils import run_sync_in_thread
        assert callable(run_sync_in_thread)
