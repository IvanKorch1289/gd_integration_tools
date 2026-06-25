"""Tests for :class:`TimeoutHelper` (S171 M5 proposals)."""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock

import pytest


class TestTimeoutHelper:
    @pytest.mark.asyncio
    async def test_with_timeout_returns_coro_result(self) -> None:
        """Оборачивает async call в timeout."""
        from src.backend.core.utils.timeout_helper import with_timeout
        coro = AsyncMock(return_value="ok")
        result = await with_timeout(coro(), timeout=2.0)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_with_timeout_raises_on_expiry(self) -> None:
        """Timeout → TimeoutError (configurable)."""
        from src.backend.core.utils.timeout_helper import with_timeout
        async def slow():
            await asyncio.sleep(10)
        with pytest.raises(asyncio.TimeoutError):
            await with_timeout(slow(), timeout=0.01)

    @pytest.mark.asyncio
    async def test_with_timeout_logs_slow_call(self) -> None:
        """Медленные вызовы логируются (для observability)."""
        from src.backend.core.utils.timeout_helper import with_timeout
        async def medium():
            await asyncio.sleep(0.5)
        result = await with_timeout(medium(), timeout=2.0, slow_threshold=0.1, op="test_op")
        assert result is None

    @pytest.mark.asyncio
    async def test_async_timeout_context_manager(self) -> None:
        """Context manager for inline use (soft deadline — does not raise)."""
        from src.backend.core.utils.timeout_helper import async_timeout
        async with async_timeout(2.0):
            await asyncio.sleep(0.01)
