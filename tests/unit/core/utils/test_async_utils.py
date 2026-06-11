"""Tests for src.backend.core.utils.async_utils."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.utils.async_utils import (
    ASYNCER_AVAILABLE,
    async_with_timeout,
    gather_with_timeout,
    run_sync_in_thread,
    task_group_tolerant,
)


@pytest.mark.unit
class TestRunSyncInThread:
    def test_asyncer_availability_flag(self) -> None:
        assert isinstance(ASYNCER_AVAILABLE, bool)

    @pytest.mark.asyncio
    async def test_run_sync_function(self) -> None:
        def sync_add(a: int, b: int) -> int:
            return a + b

        result = await run_sync_in_thread(sync_add, 2, 3)
        assert result == 5

    @pytest.mark.asyncio
    async def test_run_sync_with_kwargs(self) -> None:
        def sync_greet(name: str, greeting: str = "hello") -> str:
            return f"{greeting} {name}"

        result = await run_sync_in_thread(sync_greet, "world", greeting="hi")
        assert result == "hi world"


@pytest.mark.unit
class TestGatherWithTimeout:
    @pytest.mark.asyncio
    async def test_gather_success(self) -> None:
        async def coro(val: int) -> int:
            return val

        results = await gather_with_timeout([coro(1), coro(2), coro(3)], timeout=5.0)
        assert results == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_gather_with_exception(self) -> None:
        async def good() -> str:
            return "ok"

        async def bad() -> str:
            raise ValueError("oops")

        results = await gather_with_timeout(
            [good(), bad()], timeout=5.0, return_exceptions=True
        )
        assert results[0] == "ok"
        assert isinstance(results[1], ValueError)

    @pytest.mark.asyncio
    async def test_gather_timeout_raises(self) -> None:
        async def slow() -> str:
            await asyncio.sleep(0.1)
            return "too late"

        with pytest.raises(asyncio.TimeoutError):
            await gather_with_timeout([slow()], timeout=0.01)


@pytest.mark.unit
class TestAsyncWithTimeout:
    @pytest.mark.asyncio
    async def test_returns_result_on_time(self) -> None:
        async def coro() -> str:
            return "ok"

        result = await async_with_timeout(coro(), timeout=5.0)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_returns_default_on_timeout(self) -> None:
        async def slow() -> str:
            await asyncio.sleep(0.1)
            return "too late"

        result = await async_with_timeout(slow(), timeout=0.01, default="fallback")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_returns_none_default_on_timeout(self) -> None:
        async def slow() -> str:
            await asyncio.sleep(0.1)
            return "too late"

        result = await async_with_timeout(slow(), timeout=0.01)
        assert result is None


@pytest.mark.unit
class TestTaskGroupTolerant:
    @pytest.mark.asyncio
    async def test_all_success(self) -> None:
        async def coro(val: int) -> int:
            return val

        results = await task_group_tolerant([coro(1), coro(2)])
        assert results == [1, 2]

    @pytest.mark.asyncio
    async def test_mixed_success_and_exception(self) -> None:
        async def good() -> str:
            return "ok"

        async def bad() -> str:
            raise RuntimeError("fail")

        results = await task_group_tolerant([good(), bad()])
        assert results[0] == "ok"
        assert isinstance(results[1], RuntimeError)

    @pytest.mark.asyncio
    async def test_all_exceptions(self) -> None:
        async def bad1() -> str:
            raise ValueError("a")

        async def bad2() -> str:
            raise TypeError("b")

        results = await task_group_tolerant([bad1(), bad2()])
        assert isinstance(results[0], ValueError)
        assert isinstance(results[1], TypeError)

    @pytest.mark.asyncio
    async def test_empty_list(self) -> None:
        results = await task_group_tolerant([])
        assert results == []
