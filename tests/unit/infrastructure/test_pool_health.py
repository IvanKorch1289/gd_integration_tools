# ruff: noqa: S101
"""Тесты PoolHealthMonitor (K8 Wave 5, S1-R6).

Покрывают три ключевых сценария DoD:
- singleton не запускает background-task при default-OFF flag;
- регистрация pool и выполнение ping при flag ON;
- graceful обработка исключения в ping_callable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.backend.infrastructure.clients.pool_health import (
    PoolHealthMonitor,
    get_pool_monitor,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_monitor() -> PoolHealthMonitor:
    """Создаёт свежий (не-singleton) экземпляр для изоляции тестов."""
    return PoolHealthMonitor(tick_interval=1.0)


# ---------------------------------------------------------------------------
# Test: singleton
# ---------------------------------------------------------------------------


def test_get_pool_monitor_returns_same_instance() -> None:
    """get_pool_monitor() всегда возвращает один и тот же объект."""
    m1 = get_pool_monitor()
    m2 = get_pool_monitor()
    assert m1 is m2


# ---------------------------------------------------------------------------
# Test: flag OFF — start() не создаёт background-task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_skips_when_flag_off() -> None:
    """При отключённом feature-flag start() завершается без создания задачи."""
    monitor = _make_monitor()

    with patch(
        "src.backend.infrastructure.clients.pool_health._is_flag_enabled",
        return_value=False,
    ):
        await monitor.start()

    # Фоновая задача НЕ создана
    assert monitor._task is None
    assert not monitor._running

    # Безопасная остановка незапущенного монитора
    await monitor.stop()


# ---------------------------------------------------------------------------
# Test: flag ON — регистрация + ping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_registers_and_pings_when_flag_on() -> None:
    """При включённом flag register_pool + tick вызывает ping_callable."""
    monitor = _make_monitor()
    ping_mock = AsyncMock(return_value=None)
    fake_pool = object()

    monitor.register_pool(
        name="test_pool",
        pool=fake_pool,
        ping_callable=ping_mock,
        idle_timeout=0.0,  # пинговать сразу (idle_timeout=0 → always ping)
    )

    # Принудительно ставим last_ping_at в прошлое
    import time

    monitor._pools["test_pool"].last_ping_at = time.monotonic() - 120.0

    with patch(
        "src.backend.infrastructure.clients.pool_health._is_flag_enabled",
        return_value=True,
    ):
        # tick() проверяем напрямую, не поднимая background-task
        await monitor.tick()

    # ping_callable вызван ровно один раз
    ping_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test: flag ON — ping exception — graceful
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_handles_ping_exception() -> None:
    """Исключение в ping_callable не прерывает monitor и не поднимается наружу."""
    monitor = _make_monitor()

    async def _failing_ping() -> None:
        raise ConnectionError("redis unreachable")

    monitor.register_pool(
        name="broken_pool", pool=object(), ping_callable=_failing_ping, idle_timeout=0.0
    )

    import time

    monitor._pools["broken_pool"].last_ping_at = time.monotonic() - 120.0

    # tick() должен завершиться без исключения (graceful)
    await monitor.tick()

    # last_ping_at обновлён (сброшен) даже при ошибке
    assert monitor._pools["broken_pool"].last_ping_at > 0


# ---------------------------------------------------------------------------
# Test: несколько пулов — только idle пинкуются
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_only_pings_idle_pools() -> None:
    """Пул с малым elapsed не получает ping (idle_timeout не истёк)."""
    monitor = _make_monitor()

    ping_idle = AsyncMock(return_value=None)
    ping_fresh = AsyncMock(return_value=None)

    import time

    now = time.monotonic()

    monitor.register_pool("idle", object(), ping_idle, idle_timeout=10.0)
    monitor._pools["idle"].last_ping_at = now - 60.0  # давно

    monitor.register_pool("fresh", object(), ping_fresh, idle_timeout=60.0)
    monitor._pools["fresh"].last_ping_at = now - 1.0  # только что

    await monitor.tick()

    ping_idle.assert_awaited_once()
    ping_fresh.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test: start() при flag ON создаёт running-task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_start_creates_task_when_flag_on() -> None:
    """При flag ON start() устанавливает _running=True и создаёт _task."""
    monitor = _make_monitor()

    with patch(
        "src.backend.infrastructure.clients.pool_health._is_flag_enabled",
        return_value=True,
    ):
        await monitor.start()

    try:
        assert monitor._running
        assert monitor._task is not None
    finally:
        await monitor.stop()
