"""Unit-тесты ``TaskRegistry`` + ``Watchdog`` (V15 R-V15-11)."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
import contextvars

import pytest

from src.backend.core.utils.task_registry import (
    TaskRegistry,
    get_task_registry,
    reset_task_registry,
)
from src.backend.core.utils.watchdog import Watchdog


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Каждый тест получает свежий singleton."""
    reset_task_registry()
    yield
    reset_task_registry()


@pytest.mark.asyncio
async def test_create_task_registers_in_set() -> None:
    """``create_task`` добавляет таску в ``list_tasks``."""
    registry = TaskRegistry()

    async def _worker() -> int:
        await asyncio.sleep(0.05)
        return 42

    task = registry.create_task(_worker(), name="t1")
    live = registry.list_tasks()
    assert task in live

    result = await task
    assert result == 42
    # После завершения таска удаляется из реестра.
    assert task not in registry.list_tasks()


@pytest.mark.asyncio
async def test_shutdown_all_cancels_pending() -> None:
    """``shutdown_all`` отменяет живые задачи."""
    registry = TaskRegistry()

    async def _worker() -> None:
        await asyncio.sleep(60)

    task = registry.create_task(_worker(), name="long")
    assert not task.done()

    await registry.shutdown_all(timeout=2)
    assert task.done()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_shutdown_all_waits_completed() -> None:
    """``shutdown_all`` отдаёт уже завершённые таски корректно."""
    registry = TaskRegistry()

    async def _quick() -> str:
        return "ok"

    task = registry.create_task(_quick(), name="quick")
    await asyncio.sleep(0)  # дать event loop шанс выполнить
    await asyncio.sleep(0)
    await registry.shutdown_all(timeout=1)
    assert task.done()
    # Завершённая задача не должна быть отменена.
    assert not task.cancelled()


@pytest.mark.asyncio
async def test_correlation_id_propagation() -> None:
    """ContextVars каскадируются в фоновую таску через copy_context."""
    var: contextvars.ContextVar[str] = contextvars.ContextVar("test_var", default="")
    var.set("hello")

    registry = TaskRegistry()

    captured: dict[str, str] = {}

    async def _worker() -> None:
        captured["value"] = var.get()

    task = registry.create_task(_worker(), name="ctx")
    await task
    assert captured["value"] == "hello"


@pytest.mark.asyncio
async def test_cancel_by_name() -> None:
    """``cancel(name)`` возвращает True, если задача найдена."""
    registry = TaskRegistry()

    async def _worker() -> None:
        await asyncio.sleep(60)

    registry.create_task(_worker(), name="ctl")
    assert registry.cancel("ctl") is True
    assert registry.cancel("missing") is False
    await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_deadline_expiry_escalates_via_watchdog() -> None:
    """``deadline_seconds`` заставляет Watchdog отменить задачу."""
    registry = TaskRegistry()

    async def _slow() -> None:
        await asyncio.sleep(5)

    task = registry.create_task(_slow(), name="slow", deadline_seconds=0.05)
    with pytest.raises(asyncio.TimeoutError):
        await task


@pytest.mark.asyncio
async def test_singleton_returns_same_instance() -> None:
    """``get_task_registry`` возвращает один и тот же объект."""
    a = get_task_registry()
    b = get_task_registry()
    assert a is b


@pytest.mark.asyncio
async def test_watchdog_wrap_passes_through() -> None:
    """``Watchdog.wrap`` корректно возвращает результат."""
    wd = Watchdog(name="wd-test", deadline_seconds=1.0)

    async def _quick() -> int:
        return 7

    assert await wd.wrap(_quick()) == 7


@pytest.mark.asyncio
async def test_create_after_shutdown_raises() -> None:
    """После ``shutdown_all`` нельзя создавать новые задачи."""
    registry = TaskRegistry()
    await registry.shutdown_all(timeout=0.1)
    with pytest.raises(RuntimeError):
        registry.create_task(asyncio.sleep(0), name="post-shutdown")
