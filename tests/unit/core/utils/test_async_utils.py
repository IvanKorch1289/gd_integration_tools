"""T-P0.1.11: unit-тесты для core/utils/async_utils.py (run_sync_in_thread, gather_with_timeout, async_with_timeout, task_group_tolerant).

Coverage: async_utils.py 61% → 95%+.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.utils.async_utils import (
    ASYNCER_AVAILABLE,
    async_with_timeout,
    gather_with_timeout,
    run_sync_in_thread,
    task_group_tolerant,
)


class TestRunSyncInThread:
    @pytest.mark.asyncio
    async def test_with_asyncer(self) -> None:
        """Если ASYNCER_AVAILABLE — используется asyncer.asyncify."""
        # asyncer установлен в venv (если нет — тест skip)
        if not ASYNCER_AVAILABLE:
            pytest.skip("asyncer не установлен")

        def add(a: int, b: int) -> int:
            return a + b

        result = await run_sync_in_thread(add, 2, 3)
        assert result == 5

    @pytest.mark.asyncio
    async def test_with_kwargs(self) -> None:
        if not ASYNCER_AVAILABLE:
            pytest.skip("asyncer не установлен")

        def greet(name: str, prefix: str = "Hi") -> str:
            return f"{prefix}, {name}!"

        result = await run_sync_in_thread(greet, "World", prefix="Hello")
        assert result == "Hello, World!"

    @pytest.mark.asyncio
    async def test_fallback_to_to_thread(self) -> None:
        """Если ASYNCER_AVAILABLE=False → asyncio.to_thread."""
        with patch(
            "src.backend.core.utils.async_utils.ASYNCER_AVAILABLE", False
        ):
            def add(a: int, b: int) -> int:
                return a + b

            result = await run_sync_in_thread(add, 10, 20)
            assert result == 30

    @pytest.mark.asyncio
    async def test_fallback_with_kwargs(self) -> None:
        with patch(
            "src.backend.core.utils.async_utils.ASYNCER_AVAILABLE", False
        ):
            def multiply(x: int, factor: int = 2) -> int:
                return x * factor

            result = await run_sync_in_thread(multiply, 5, factor=3)
            assert result == 15


class TestGatherWithTimeout:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        async def task(value: int) -> int:
            await asyncio.sleep(0.01)
            return value

        results = await gather_with_timeout(
            [task(1), task(2), task(3)], timeout=1.0
        )
        assert results == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_timeout_raises(self) -> None:
        async def slow() -> None:
            await asyncio.sleep(10)

        with patch("src.backend.core.utils.async_utils.logger") as mock_logger:
            with pytest.raises(asyncio.TimeoutError):
                await gather_with_timeout([slow()], timeout=0.01)
            assert mock_logger.warning.called

    @pytest.mark.asyncio
    async def test_return_exceptions_true(self) -> None:
        async def ok() -> int:
            return 1

        async def fail() -> int:
            raise ValueError("boom")

        # return_exceptions=True (default) — exception в списке, не raise
        results = await gather_with_timeout(
            [ok(), fail()], timeout=1.0, return_exceptions=True
        )
        assert results[0] == 1
        assert isinstance(results[1], ValueError)

    @pytest.mark.asyncio
    async def test_return_exceptions_false(self) -> None:
        async def fail() -> int:
            raise ValueError("boom")

        # return_exceptions=False — exception raise
        with pytest.raises(ValueError, match="boom"):
            await gather_with_timeout(
                [fail()], timeout=1.0, return_exceptions=False
            )

    @pytest.mark.asyncio
    async def test_empty_coros(self) -> None:
        results = await gather_with_timeout([], timeout=1.0)
        assert results == []


class TestAsyncWithTimeout:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        async def quick() -> str:
            return "fast"

        result = await async_with_timeout(quick(), timeout=1.0)
        assert result == "fast"

    @pytest.mark.asyncio
    async def test_timeout_returns_default(self) -> None:
        async def slow() -> None:
            await asyncio.sleep(10)

        result = await async_with_timeout(
            slow(), timeout=0.01, default="default-value"
        )
        assert result == "default-value"

    @pytest.mark.asyncio
    async def test_timeout_default_none(self) -> None:
        async def slow() -> None:
            await asyncio.sleep(10)

        result = await async_with_timeout(slow(), timeout=0.01)
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_propagates(self) -> None:
        """Нет TimeoutError — другие исключения propagate."""
        async def fail() -> str:
            raise ValueError("immediate-fail")

        with pytest.raises(ValueError, match="immediate-fail"):
            await async_with_timeout(fail(), timeout=1.0)


class TestTaskGroupTolerant:
    @pytest.mark.asyncio
    async def test_all_success(self) -> None:
        async def task(v: int) -> int:
            await asyncio.sleep(0.01)
            return v

        results = await task_group_tolerant([task(1), task(2), task(3)])
        assert results == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_one_fails_others_continue(self) -> None:
        """Tolerant: один task fails, остальные возвращают результат."""
        async def ok() -> int:
            await asyncio.sleep(0.01)
            return 42

        async def fail() -> int:
            raise ValueError("oops")

        results = await task_group_tolerant([ok(), fail(), ok()])
        assert results[0] == 42
        assert isinstance(results[1], ValueError)
        assert results[2] == 42

    @pytest.mark.asyncio
    async def test_empty(self) -> None:
        results = await task_group_tolerant([])
        assert results == []


class TestAllExports:
    def test_all(self) -> None:
        from src.backend.core.utils import async_utils as a

        assert set(a.__all__) == {
            "run_sync_in_thread",
            "gather_with_timeout",
            "async_with_timeout",
            "task_group_tolerant",
        }
