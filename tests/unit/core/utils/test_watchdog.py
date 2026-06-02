"""T-P0.1.9: unit-тесты для core/utils/watchdog.py (Watchdog).

Coverage: watchdog.py 43% → 90%+ через тестирование:
- __init__ (state)
- wrap (success, timeout, awaitable)
- _capture_sentry (no SDK, with SDK, SDK raises)
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.utils.watchdog import Watchdog


class TestInit:
    def test_stores_name_and_deadline(self) -> None:
        wd = Watchdog(name="test-wd", deadline_seconds=5.0)
        assert wd.name == "test-wd"
        assert wd.deadline_seconds == 5.0

    def test_all(self) -> None:
        from src.backend.core.utils import watchdog as w

        assert w.__all__ == ("Watchdog",)


class TestWrapSuccess:
    @pytest.mark.asyncio
    async def test_returns_value(self) -> None:
        wd = Watchdog(name="success", deadline_seconds=1.0)

        async def quick() -> str:
            return "done"

        result = await wd.wrap(quick())
        assert result == "done"

    @pytest.mark.asyncio
    async def test_with_awaitable(self) -> None:
        """wrap принимает Awaitable (не только Coroutine)."""
        wd = Watchdog(name="awaitable-test", deadline_seconds=1.0)
        future: asyncio.Future[int] = asyncio.get_event_loop().create_future()
        future.set_result(42)
        result = await wd.wrap(future)
        assert result == 42


class TestWrapTimeout:
    @pytest.mark.asyncio
    async def test_timeout_raises(self) -> None:
        wd = Watchdog(name="slow", deadline_seconds=0.01)

        async def slow_coro() -> None:
            await asyncio.sleep(10)

        with pytest.raises(asyncio.TimeoutError):
            await wd.wrap(slow_coro())

    @pytest.mark.asyncio
    async def test_timeout_logs_warning(self) -> None:
        wd = Watchdog(name="logged", deadline_seconds=0.01)

        async def slow() -> None:
            await asyncio.sleep(10)

        with patch("src.backend.core.utils.watchdog._logger") as mock_logger:
            with pytest.raises(asyncio.TimeoutError):
                await wd.wrap(slow())
            assert mock_logger.warning.called
            call_kwargs = mock_logger.warning.call_args
            assert call_kwargs.args[0] == "watchdog.deadline_exceeded"
            assert call_kwargs.kwargs["extra"]["task_name"] == "logged"
            assert call_kwargs.kwargs["extra"]["deadline_seconds"] == 0.01

    @pytest.mark.asyncio
    async def test_timeout_calls_capture_sentry(self) -> None:
        wd = Watchdog(name="sentry-test", deadline_seconds=0.01)

        async def slow() -> None:
            await asyncio.sleep(10)

        with patch.object(wd, "_capture_sentry") as mock_capture:
            with pytest.raises(asyncio.TimeoutError):
                await wd.wrap(slow())
            assert mock_capture.called


class TestCaptureSentry:
    def test_no_sentry_sdk_returns_silently(self) -> None:
        """Если sentry_sdk не установлен — ImportError → return."""
        wd = Watchdog(name="no-sentry", deadline_seconds=1.0)
        # Удаляем sentry_sdk из sys.modules если есть, и блокируем import
        with patch.dict(sys.modules, {"sentry_sdk": None}):
            # Прямой вызов — вернёт None
            assert wd._capture_sentry() is None

    def test_with_sentry_sdk(self) -> None:
        """Если sentry_sdk доступен — capture_message вызван."""
        wd = Watchdog(name="with-sentry", deadline_seconds=1.0)
        mock_sentry = MagicMock()
        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            wd._capture_sentry()
            assert mock_sentry.capture_message.called
            call_args = mock_sentry.capture_message.call_args
            assert "with-sentry" in call_args.args[0]
            assert call_args.kwargs["level"] == "warning"

    def test_sentry_sdk_raises_returns_silently(self) -> None:
        """Если sentry_sdk.capture_message raises — return без exception."""
        wd = Watchdog(name="sentry-raises", deadline_seconds=1.0)
        mock_sentry = MagicMock()
        mock_sentry.capture_message.side_effect = RuntimeError("sentry down")
        with patch.dict(sys.modules, {"sentry_sdk": mock_sentry}):
            # Не должно raise
            assert wd._capture_sentry() is None
