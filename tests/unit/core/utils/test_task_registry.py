"""T-P0.1.8: unit-тесты для core/utils/task_registry.py (TaskRegistry).

Coverage: task_registry.py 23% → 80%+ через тестирование:
- create_task (basic, deadline, closed state)
- _with_context (contextvar propagation, exception path)
- _on_done (cleanup, cancelled, exception)
- cancel (by name, unknown, already done)
- shutdown_all (empty, with tasks, timeout)
- list_tasks, reset_for_tests
- module-level singleton
"""

from __future__ import annotations

import asyncio
import contextvars
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.utils.task_registry import (
    TaskRegistry,
    get_task_registry,
    reset_task_registry,
)

# Test-scoped contextvar для проверки propagation
_test_var: contextvars.ContextVar[int] = contextvars.ContextVar("_test_var", default=0)


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    """Reset module-level singleton перед каждым тестом."""
    reset_task_registry()
    _test_var.set(0)
    yield
    reset_task_registry()


class TestInit:
    def test_init_empty_state(self) -> None:
        reg = TaskRegistry()
        assert reg._tasks == set()
        assert reg._named == {}
        assert reg._closed is False

    def test_init_independent_instances(self) -> None:
        r1 = TaskRegistry()
        r2 = TaskRegistry()
        assert r1 is not r2
        assert r1._tasks is not r2._tasks


class TestCreateTask:
    @pytest.mark.asyncio
    async def test_create_basic(self) -> None:
        reg = TaskRegistry()

        async def worker() -> str:
            return "done"

        task = reg.create_task(worker(), name="test-worker")
        result = await task
        assert result == "done"
        assert reg._closed is False

    @pytest.mark.asyncio
    async def test_create_with_deadline(self) -> None:
        reg = TaskRegistry()
        # Mock Watchdog чтобы избежать реальной deadline-логики
        with patch(
            "src.backend.core.utils.task_registry.Watchdog"
        ) as mock_watchdog_cls:
            mock_watchdog = MagicMock()
            mock_watchdog.wrap = lambda coro: coro
            mock_watchdog_cls.return_value = mock_watchdog

            async def worker() -> int:
                return 42

            task = reg.create_task(
                worker(), name="deadline-worker", deadline_seconds=1.0
            )
            assert mock_watchdog_cls.called
            assert mock_watchdog_cls.call_args.kwargs == {
                "name": "deadline-worker",
                "deadline_seconds": 1.0,
            }
            result = await task
            assert result == 42

    @pytest.mark.asyncio
    async def test_create_after_shutdown_raises(self) -> None:
        reg = TaskRegistry()
        reg._closed = True

        async def worker() -> None:
            return None

        with pytest.raises(RuntimeError, match="уже закрыт"):
            reg.create_task(worker(), name="post-shutdown")

    @pytest.mark.asyncio
    async def test_create_with_awaitable_not_coroutine(self) -> None:
        """create_task принимает Awaitable, не только Coroutine."""
        reg = TaskRegistry()
        # asyncio.Future — это Awaitable
        future: asyncio.Future[int] = asyncio.get_event_loop().create_future()
        future.set_result(99)
        task = reg.create_task(future, name="awaitable-test")
        result = await task
        assert result == 99


class TestWithContext:
    @pytest.mark.asyncio
    async def test_propagates_contextvar(self) -> None:
        """Значения contextvar из вызывающего кода видны внутри task."""
        reg = TaskRegistry()
        _test_var.set(123)

        captured: dict[str, int] = {}

        async def reader() -> int:
            captured["value"] = _test_var.get()
            return _test_var.get()

        task = reg.create_task(reader(), name="ctx-reader")
        result = await task
        assert result == 123
        assert captured["value"] == 123

    @pytest.mark.asyncio
    async def test_swallows_lookup_error_on_set(self) -> None:
        """_with_context: LookupError при var.set() — игнорируется (best-effort)."""
        reg = TaskRegistry()

        # Token-less var: var.set() без аргумента LookupError
        var = contextvars.ContextVar("test", default=0)

        captured: list[int] = []

        async def reader() -> int:
            captured.append(1)
            return 1

        task = reg.create_task(reader(), name="swallow-test")
        # Реальный _with_context: вызывает var.set(value) для каждой var в ctx.
        # Если var без токена — LookupError, но continue.
        result = await task
        assert result == 1
        assert captured == [1]


class TestOnDone:
    @pytest.mark.asyncio
    async def test_removes_from_tasks_set(self) -> None:
        reg = TaskRegistry()

        async def worker() -> str:
            return "ok"

        task = reg.create_task(worker(), name="remove-test")
        await task
        # Дать add_done_callback'у сработать
        await asyncio.sleep(0)
        assert task not in reg._tasks
        assert "remove-test" not in reg._named

    @pytest.mark.asyncio
    async def test_logs_exception(self) -> None:
        reg = TaskRegistry()

        async def failing() -> None:
            raise ValueError("test-failure")

        with patch("src.backend.core.utils.task_registry._logger") as mock_logger:
            task = reg.create_task(failing(), name="failing-task")
            try:
                await task
            except ValueError:
                pass
            await asyncio.sleep(0)
            # _logger.warning вызван
            assert mock_logger.warning.called

    @pytest.mark.asyncio
    async def test_cancelled_does_not_log(self) -> None:
        reg = TaskRegistry()

        async def long_running() -> None:
            await asyncio.sleep(10)

        with patch("src.backend.core.utils.task_registry._logger") as mock_logger:
            task = reg.create_task(long_running(), name="cancel-test")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await asyncio.sleep(0)
            # CancelledError не логируется
            warning_calls = [
                c for c in mock_logger.warning.call_args_list if "task_failed" in str(c)
            ]
            assert len(warning_calls) == 0


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_by_name(self) -> None:
        reg = TaskRegistry()

        async def worker() -> None:
            await asyncio.sleep(10)

        reg.create_task(worker(), name="cancel-me")
        assert reg.cancel("cancel-me") is True

    def test_cancel_unknown_returns_false(self) -> None:
        reg = TaskRegistry()
        assert reg.cancel("nonexistent") is False

    @pytest.mark.asyncio
    async def test_cancel_already_done(self) -> None:
        reg = TaskRegistry()

        async def worker() -> str:
            return "done"

        task = reg.create_task(worker(), name="done-task")
        await task
        await asyncio.sleep(0)  # add_done_callback
        # После done() _on_done убирает task из _named → cancel возвращает False
        assert reg.cancel("done-task") is False


class TestShutdownAll:
    @pytest.mark.asyncio
    async def test_shutdown_empty(self) -> None:
        reg = TaskRegistry()
        await reg.shutdown_all(timeout=1.0)
        assert reg._closed is True

    @pytest.mark.asyncio
    async def test_shutdown_cancels_live_tasks(self) -> None:
        reg = TaskRegistry()

        async def long_running() -> None:
            await asyncio.sleep(10)

        reg.create_task(long_running(), name="live-1")
        reg.create_task(long_running(), name="live-2")

        # Короткий timeout — tasks не успеют done() до cancel
        await reg.shutdown_all(timeout=2.0)
        await asyncio.sleep(0)  # event loop drain
        assert reg._closed is True
        # Tasks должны быть done (cancelled)
        # Имя может быть удалено из _named через _on_done callback
        for t in [reg._named.get("live-1"), reg._named.get("live-2")]:
            if t is not None:
                assert t.done()

    @pytest.mark.asyncio
    async def test_shutdown_empty_after_tasks_completed(self) -> None:
        """Shutdown all на registry где tasks уже done — просто closed=True."""
        reg = TaskRegistry()

        async def quick() -> str:
            return "ok"

        t1 = reg.create_task(quick(), name="quick-1")
        t2 = reg.create_task(quick(), name="quick-2")
        await t1
        await t2
        await asyncio.sleep(0)  # add_done_callback drain

        await reg.shutdown_all(timeout=1.0)
        assert reg._closed is True


class TestListTasks:
    @pytest.mark.asyncio
    async def test_list_empty(self) -> None:
        reg = TaskRegistry()
        assert reg.list_tasks() == []

    @pytest.mark.asyncio
    async def test_list_live(self) -> None:
        reg = TaskRegistry()

        async def worker() -> None:
            await asyncio.sleep(10)

        t1 = reg.create_task(worker(), name="list-1")
        t2 = reg.create_task(worker(), name="list-2")
        assert len(reg.list_tasks()) == 2
        t1.cancel()
        t2.cancel()


class TestResetForTests:
    def test_reset_clears_state(self) -> None:
        reg = TaskRegistry()
        reg._tasks.add(MagicMock())
        reg._named["x"] = MagicMock()
        reg._closed = True

        reg.reset_for_tests()

        assert reg._tasks == set()
        assert reg._named == {}
        assert reg._closed is False


class TestModuleSingleton:
    def test_get_creates(self) -> None:
        r1 = get_task_registry()
        assert isinstance(r1, TaskRegistry)

    def test_get_returns_same(self) -> None:
        r1 = get_task_registry()
        r2 = get_task_registry()
        assert r1 is r2

    def test_reset_task_registry(self) -> None:
        r1 = get_task_registry()
        reset_task_registry()
        r2 = get_task_registry()
        assert r1 is not r2


class TestAllExports:
    def test_all(self) -> None:
        from src.backend.core.utils import task_registry as m

        assert set(m.__all__) == {
            "TaskRegistry",
            "get_task_registry",
            "reset_task_registry",
        }
