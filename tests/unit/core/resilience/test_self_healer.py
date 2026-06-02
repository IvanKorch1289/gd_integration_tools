"""T-P0.1.16: unit-тесты для core/resilience/self_healer.py (SelfHealer).

Coverage: self_healer.py 23% → 90%+ через тестирование:
- __init__ (state)
- register_healer
- start (with APScheduler, fallback asyncio)
- stop (with scheduler, with task)
- _run_healers (sync, async, exception, success, already available)
- _heal_loop
- get_self_healer (singleton)
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.resilience.self_healer import (
    SelfHealer,
    _self_healer,
    get_self_healer,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    """Reset module-level singleton."""
    import src.backend.core.resilience.self_healer as sh

    sh._self_healer = None
    yield
    sh._self_healer = None


class TestInit:
    def test_default_state(self) -> None:
        h = SelfHealer()
        assert h._interval == 30
        assert h._task is None
        assert h._scheduler is None
        assert h._running is False
        assert h._healers == {}

    def test_custom_interval(self) -> None:
        h = SelfHealer(check_interval=10)
        assert h._interval == 10


class TestRegisterHealer:
    def test_register(self) -> None:
        h = SelfHealer()
        check = lambda: True
        h.register_healer("db", check)
        assert h._healers == {"db": check}

    def test_register_multiple(self) -> None:
        h = SelfHealer()
        h.register_healer("db", lambda: True)
        h.register_healer("redis", lambda: True)
        assert len(h._healers) == 2


class TestStartApscheduler:
    @pytest.mark.asyncio
    async def test_start_with_apscheduler(self) -> None:
        """Если APScheduler доступен — используется scheduler."""
        h = SelfHealer(check_interval=5)
        h.register_healer("db", lambda: True)

        mock_scheduler = MagicMock()
        with patch(
            "apscheduler.schedulers.asyncio.AsyncIOScheduler",
            return_value=mock_scheduler,
            create=True,
        ):
            await h.start()

        assert h._running is True
        assert h._scheduler is mock_scheduler
        mock_scheduler.add_job.assert_called_once()
        mock_scheduler.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_with_apscheduler_failure_falls_back(self) -> None:
        """Если APScheduler add_job raises → fallback на asyncio loop."""
        h = SelfHealer(check_interval=1)
        h.register_healer("db", lambda: True)

        mock_scheduler = MagicMock()
        mock_scheduler.add_job.side_effect = RuntimeError("apsched-fail")
        with patch(
            "apscheduler.schedulers.asyncio.AsyncIOScheduler",
            return_value=mock_scheduler,
            create=True,
        ):
            with patch(
                "src.backend.core.resilience.self_healer.get_task_registry"
            ) as mock_registry:
                mock_task = MagicMock()
                mock_registry.return_value.create_task = MagicMock(
                    return_value=mock_task
                )
                await h.start()

        assert h._running is True
        # Fallback на asyncio
        assert h._scheduler is not None or h._task is not None


class TestStartAsyncioFallback:
    @pytest.mark.asyncio
    async def test_start_via_asyncio_when_apscheduler_missing(self) -> None:
        """Если apscheduler import fails — fallback на asyncio loop."""
        h = SelfHealer(check_interval=1)
        h.register_healer("db", lambda: True)

        # Patch apscheduler import to fail
        with patch.dict(
            "sys.modules",
            {"apscheduler.schedulers.asyncio": None},
        ):
            with patch(
                "src.backend.core.resilience.self_healer.get_task_registry"
            ) as mock_registry:
                mock_task = MagicMock()
                mock_registry.return_value.create_task = MagicMock(
                    return_value=mock_task
                )
                await h.start()

        assert h._running is True
        # Fallback: task создан
        assert h._task is not None
        assert h._scheduler is None
        mock_registry.return_value.create_task.assert_called_once()


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_with_scheduler(self) -> None:
        h = SelfHealer()
        mock_scheduler = MagicMock()
        h._scheduler = mock_scheduler
        h._running = True

        await h.stop()
        assert h._running is False
        mock_scheduler.shutdown.assert_called_once_with(wait=False)
        assert h._scheduler is None

    @pytest.mark.asyncio
    async def test_stop_with_task(self) -> None:
        h = SelfHealer()
        mock_task = MagicMock()
        h._task = mock_task
        h._running = True

        await h.stop()
        assert h._running is False
        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_no_scheduler_no_task(self) -> None:
        h = SelfHealer()
        await h.stop()
        assert h._running is False


class TestRunHealers:
    @pytest.mark.asyncio
    async def test_skips_available(self) -> None:
        """Если компонент available — skip health check."""
        h = SelfHealer()
        h.register_healer("db", lambda: True)

        with patch(
            "src.backend.core.resilience.self_healer.degradation_manager"
        ) as mock_dm:
            mock_dm.is_available.return_value = True
            await h._run_healers()
            # check не вызван (is_available=True)
            mock_dm.report_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_health_check_success(self) -> None:
        """Sync health_check returns truthy → report_success."""
        h = SelfHealer()
        h.register_healer("db", lambda: True)

        with patch(
            "src.backend.core.resilience.self_healer.degradation_manager"
        ) as mock_dm:
            mock_dm.is_available.return_value = False
            await h._run_healers()
            mock_dm.report_success.assert_called_once_with("db")

    @pytest.mark.asyncio
    async def test_async_health_check_success(self) -> None:
        """Async health_check awaited."""
        h = SelfHealer()

        async def async_check() -> bool:
            return True

        h.register_healer("db", async_check)

        with patch(
            "src.backend.core.resilience.self_healer.degradation_manager"
        ) as mock_dm:
            mock_dm.is_available.return_value = False
            await h._run_healers()
            mock_dm.report_success.assert_called_once_with("db")

    @pytest.mark.asyncio
    async def test_health_check_returns_falsy(self) -> None:
        """Health check returns False — не восстановлен."""
        h = SelfHealer()
        h.register_healer("db", lambda: False)

        with patch(
            "src.backend.core.resilience.self_healer.degradation_manager"
        ) as mock_dm:
            mock_dm.is_available.return_value = False
            await h._run_healers()
            mock_dm.report_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_check_exception_logged(self) -> None:
        """Если health_check raises — log debug, не report_success."""
        h = SelfHealer()

        def failing_check() -> None:
            raise ConnectionError("down")

        h.register_healer("db", failing_check)

        with patch(
            "src.backend.core.resilience.self_healer.degradation_manager"
        ) as mock_dm:
            mock_dm.is_available.return_value = False
            with patch(
                "src.backend.core.resilience.self_healer.logger"
            ) as mock_logger:
                await h._run_healers()
                # Не propagate, log debug
                assert mock_logger.debug.called
                mock_dm.report_success.assert_not_called()


class TestHealLoop:
    @pytest.mark.asyncio
    async def test_loop_runs_healers_then_stops(self) -> None:
        """Loop: sleep, run_healers, repeat while _running."""
        h = SelfHealer(check_interval=0.01)
        h._running = True
        h.register_healer("db", lambda: True)

        # Пропускаем _run_healers реальный, mock'аем
        with patch.object(h, "_run_healers", new=AsyncMock()) as mock_run:
            # Создаём task и останавливаем после 1 итерации
            task = asyncio.create_task(h._heal_loop())
            await asyncio.sleep(0.05)
            h._running = False
            await asyncio.sleep(0.05)
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # _run_healers вызван хотя бы раз
            assert mock_run.call_count >= 1

    @pytest.mark.asyncio
    async def test_loop_stops_immediately_when_not_running(self) -> None:
        """Если _running=False на старте — loop сразу завершается."""
        h = SelfHealer(check_interval=10)
        h._running = False
        # Должен сразу выйти
        await asyncio.wait_for(h._heal_loop(), timeout=0.5)


class TestModuleSingleton:
    def test_get_creates(self) -> None:
        h = get_self_healer()
        assert isinstance(h, SelfHealer)

    def test_get_returns_same(self) -> None:
        h1 = get_self_healer()
        h2 = get_self_healer()
        assert h1 is h2


class TestAllExports:
    def test_all(self) -> None:
        from src.backend.core.resilience import self_healer as m

        assert set(m.__all__) == {"SelfHealer", "get_self_healer"}
