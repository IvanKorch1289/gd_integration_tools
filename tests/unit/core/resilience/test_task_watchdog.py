"""Unit-тесты TaskWatchdog (V15 R-V15-11, task K3 Sprint-2 Wave 2)."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from src.backend.core.resilience.task_watchdog import (
    TaskWatchdog,
    _reset_task_watchdog,
    get_task_watchdog,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Каждый тест получает свежий singleton."""
    _reset_task_watchdog()
    yield
    _reset_task_watchdog()


# ─── Тест 1: no-op при выключенном feature-flag ─────────────────────────────


@pytest.mark.asyncio
async def test_register_noop_when_flag_off() -> None:
    """``register`` не добавляет запись, если feature-flag выключен (default)."""
    watchdog = TaskWatchdog()

    async def _dummy() -> None:
        await asyncio.sleep(60)

    task = asyncio.create_task(_dummy())
    try:
        # feature_flags.task_watchdog_deadline = False по умолчанию.
        watchdog.register(task, deadline_seconds=1.0, name="dummy")
        # Никаких регистраций нет — список пуст.
        assert watchdog._registrations == []
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: S110, BLE001
            pass


@pytest.mark.asyncio
async def test_start_noop_when_flag_off() -> None:
    """``start`` не создаёт background-task, если feature-flag выключен."""
    watchdog = TaskWatchdog()
    await watchdog.start()
    # Монитор не был запущен.
    assert watchdog._monitor_task is None


# ─── Тест 2: cancel после превышения deadline ────────────────────────────────


@pytest.mark.asyncio
async def test_tick_cancels_task_after_deadline() -> None:
    """``tick`` отменяет задачу по истечении deadline при включённом flag."""

    async def _slow() -> None:
        await asyncio.sleep(60)

    task = asyncio.create_task(_slow())
    watchdog = TaskWatchdog(cancel_on_deadline=True)

    with patch(
        "src.backend.core.config.features.feature_flags.task_watchdog_deadline",
        new=True,
    ):
        # Регистрируем с очень коротким deadline.
        watchdog.register(task, deadline_seconds=0.001, name="slow-task")
        assert len(watchdog._registrations) == 1

        # Ждём немного, чтобы elapsed > deadline.
        await asyncio.sleep(0.05)

        # Вызываем tick напрямую с feature_flags.patch в scope.
        await watchdog.tick()

    # Даём event-loop'у обработать cancel() → CancelledError доходит до задачи.
    try:
        await asyncio.wait_for(task, timeout=0.5)
    except (asyncio.CancelledError, asyncio.TimeoutError):  # noqa: BLE001
        pass

    # После tick задача должна быть отменена, список registrations — пуст.
    assert task.cancelled() or task.done()
    assert watchdog._registrations == []


# ─── Тест 3: несколько задач, часть в deadline ──────────────────────────────


@pytest.mark.asyncio
async def test_tick_keeps_alive_tasks() -> None:
    """``tick`` оставляет задачи в списке, пока deadline не истёк."""

    async def _long() -> None:
        await asyncio.sleep(60)

    task_expire = asyncio.create_task(_long())
    task_alive = asyncio.create_task(_long())

    watchdog = TaskWatchdog(cancel_on_deadline=True)

    with patch(
        "src.backend.core.config.features.feature_flags.task_watchdog_deadline",
        new=True,
    ):

        # Первая задача — очень короткий deadline (истечёт).
        watchdog.register(task_expire, deadline_seconds=0.001, name="expire")
        # Вторая задача — большой deadline (останется).
        watchdog.register(task_alive, deadline_seconds=9999.0, name="alive")

        await asyncio.sleep(0.05)
        await watchdog.tick()

    # Даём cancel() пройти через event-loop.
    try:
        await asyncio.wait_for(task_expire, timeout=0.5)
    except (asyncio.CancelledError, asyncio.TimeoutError):  # noqa: BLE001
        pass

    # Первая задача была отменена, вторая осталась.
    assert task_expire.cancelled() or task_expire.done()
    assert not task_alive.done()
    # В _registrations должна остаться только задача alive.
    assert len(watchdog._registrations) == 1
    assert watchdog._registrations[0].name == "alive"

    task_alive.cancel()
    try:
        await task_alive
    except (asyncio.CancelledError, Exception):  # noqa: S110, BLE001
        pass


# ─── Тест 4: singleton ───────────────────────────────────────────────────────


def test_singleton_returns_same_instance() -> None:
    """``get_task_watchdog`` возвращает один и тот же объект."""
    a = get_task_watchdog()
    b = get_task_watchdog()
    assert a is b
    assert isinstance(a, TaskWatchdog)


@pytest.mark.asyncio
async def test_stop_reraises_cancelled_error() -> None:
    """CancelledError при остановке monitor-task должен пробрасываться."""
    watchdog = TaskWatchdog()
    # Запускаем monitor-loop (без feature-flag — это no-op, поэтому патчим).
    with patch(
        "src.backend.core.config.features.feature_flags.task_watchdog_deadline",
        new=True,
    ):
        await watchdog.start()
        assert watchdog._monitor_task is not None
        # Отменяем задачу вручную, чтобы проверить поведение stop().
        watchdog._monitor_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await watchdog.stop()
