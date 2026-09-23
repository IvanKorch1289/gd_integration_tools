"""Focused tests for ``src.backend.core.async_utils.safe_wait``.

Coverage target: ``safe_wait.py`` 33% → 100% (Sprint 12 ratchet).

Coverage:
    - ``safe_wait_for``: success path, TimeoutError reraise, reraise=False (return None),
      operation name extraction from awaitable.
    - ``with_timeout`` (async CM): success yield, TimeoutError propagation,
      operation name extraction.
    - ``cancel_on_timeout`` decorator: propagates TimeoutWithContext on timeout,
      preserves function metadata via ``functools.wraps``.
    - ``TimeoutWithContext``: attributes (timeout, coro_name), is asyncio.TimeoutError.
"""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.async_utils.safe_wait import (
    TimeoutWithContext,
    cancel_on_timeout,
    safe_wait_for,
    with_timeout,
)


class TestTimeoutWithContext:
    """``TimeoutWithContext`` exception class."""

    def test_attributes(self) -> None:
        """timeout, coro_name сохраняются в exception."""
        e = TimeoutWithContext("test message", timeout=5.0, coro_name="my_op")
        assert e.timeout == 5.0
        assert e.coro_name == "my_op"
        assert "test message" in str(e)

    def test_inherits_from_asyncio_timeout_error(self) -> None:
        """Backward-compat: ``except TimeoutError`` ловит наш exception."""
        e = TimeoutWithContext("test", timeout=1.0, coro_name="x")
        assert isinstance(e, asyncio.TimeoutError)
        # ``except asyncio.TimeoutError`` срабатывает.
        try:
            raise e
        except TimeoutError as caught:
            assert caught is e


class TestSafeWaitFor:
    """``safe_wait_for`` — wrapper над asyncio.wait_for."""

    @pytest.mark.asyncio
    async def test_success_returns_result(self) -> None:
        """Успешный await → return result."""

        async def fast_coro() -> str:
            return "ok"

        result = await safe_wait_for(fast_coro(), timeout=1.0)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_timeout_reraises_by_default(self) -> None:
        """Default reraise=True → поднимает ``TimeoutWithContext``."""

        async def slow_coro() -> str:
            await asyncio.sleep(5.0)
            return "never"

        with pytest.raises(TimeoutWithContext) as exc_info:
            await safe_wait_for(slow_coro(), timeout=0.1)
        assert exc_info.value.timeout == 0.1

    @pytest.mark.asyncio
    async def test_timeout_returns_none_when_reraise_false(self) -> None:
        """reraise=False → return None без exception."""

        async def slow_coro() -> str:
            await asyncio.sleep(5.0)
            return "never"

        result = await safe_wait_for(slow_coro(), timeout=0.1, reraise=False)
        assert result is None

    @pytest.mark.asyncio
    async def test_operation_name_from_awaitable(self) -> None:
        """operation берётся из ``__name__`` awaitable если не передан."""

        async def my_named_coro() -> int:
            await asyncio.sleep(5.0)
            return 42

        with pytest.raises(TimeoutWithContext) as exc_info:
            await safe_wait_for(my_named_coro(), timeout=0.05)
        # ``my_named_coro.__name__`` используется как operation.
        assert exc_info.value.coro_name == "my_named_coro"

    @pytest.mark.asyncio
    async def test_operation_name_explicit_override(self) -> None:
        """Явный ``operation`` переопределяет default."""

        async def coro() -> None:
            await asyncio.sleep(5.0)

        with pytest.raises(TimeoutWithContext) as exc_info:
            await safe_wait_for(coro(), timeout=0.01, operation="explicit_op")
        assert exc_info.value.coro_name == "explicit_op"

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self) -> None:
        """``CancelledError`` (внешний cancel) НЕ проглатывается."""

        async def coro() -> str:
            await asyncio.sleep(5.0)
            return "never"

        # Запускаем coro, отменяем task, проверяем что CancelledError пробрасывается.
        task = asyncio.create_task(safe_wait_for(coro(), timeout=10.0))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestWithTimeout:
    """``with_timeout`` — async context manager."""

    @pytest.mark.asyncio
    async def test_success_yields_result(self) -> None:
        """Успешный coro_factory → yield result."""

        async def coro_factory() -> str:
            return "value"

        async with with_timeout(coro_factory, timeout=1.0) as result:
            assert result == "value"

    @pytest.mark.asyncio
    async def test_timeout_raises_with_context(self) -> None:
        """Timeout → ``TimeoutWithContext`` с operation name."""

        async def slow_factory() -> str:
            await asyncio.sleep(5.0)
            return "never"

        with pytest.raises(TimeoutWithContext) as exc_info:
            async with with_timeout(slow_factory, timeout=0.1, operation="slow_op"):
                pass
        assert exc_info.value.coro_name == "slow_op"
        assert exc_info.value.timeout == 0.1

    @pytest.mark.asyncio
    async def test_operation_name_from_coro_factory(self) -> None:
        """operation берётся из ``coro_factory.__name__`` если не передан."""

        async def named_factory() -> str:
            await asyncio.sleep(5.0)
            return "never"

        with pytest.raises(TimeoutWithContext) as exc_info:
            async with with_timeout(named_factory, timeout=0.01):
                pass
        assert exc_info.value.coro_name == "named_factory"


class TestCancelOnTimeout:
    """``cancel_on_timeout`` decorator."""

    @pytest.mark.asyncio
    async def test_decorator_success_returns_result(self) -> None:
        """Decorator wraps; успешный вызов возвращает result."""

        @cancel_on_timeout(timeout=1.0)
        async def my_func() -> str:
            return "decorated"

        result = await my_func()
        assert result == "decorated"

    @pytest.mark.asyncio
    async def test_decorator_timeout_raises(self) -> None:
        """Decorator: timeout → ``TimeoutWithContext``."""

        @cancel_on_timeout(timeout=0.01)
        async def slow_func() -> str:
            await asyncio.sleep(5.0)
            return "never"

        with pytest.raises(TimeoutWithContext) as exc_info:
            await slow_func()
        assert exc_info.value.timeout == 0.01

    @pytest.mark.asyncio
    async def test_decorator_custom_operation_name(self) -> None:
        """Decorator: ``operation`` переопределяет ``func.__name__``."""

        @cancel_on_timeout(timeout=0.01, operation="custom_op")
        async def some_func() -> str:
            await asyncio.sleep(5.0)
            return "never"

        with pytest.raises(TimeoutWithContext) as exc_info:
            await some_func()
        assert exc_info.value.coro_name == "custom_op"

    def test_decorator_preserves_metadata(self) -> None:
        """``functools.wraps`` сохраняет ``__name__`` decorated функции."""

        @cancel_on_timeout(timeout=1.0)
        async def my_function() -> None:
            return None

        # ``functools.wraps`` сохранил __name__.
        assert my_function.__name__ == "my_function"
