"""Тесты AutoScaler + BulkheadScaler + LocalProcessScaler (Sprint 4 Wave D)."""
# ruff: noqa: S101, SLF001

from __future__ import annotations

import asyncio
import signal
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.scaling.auto_scaler import AutoScaler
from src.backend.core.scaling.bulkhead_scaler import BulkheadScaler, _utilization
from src.backend.core.scaling.local_process_scaler import LocalProcessScaler
from src.backend.infrastructure.resilience.bulkhead import Bulkhead, BulkheadRegistry

# ── BulkheadScaler ──


def test_bulkhead_scaler_high_watermark_increases() -> None:
    """При utilization ≥ HW max_concurrent увеличивается на adjust_step."""
    registry = BulkheadRegistry()

    async def _setup() -> None:
        bh = await registry.get_or_create("db", max_concurrent=10)
        # Имитируем 95% utilization через consume семафора.
        sem = bh._ensure_sem()
        for _ in range(9):
            await sem.acquire()

    asyncio.run(_setup())

    scaler = BulkheadScaler(
        registry, high_watermark_pct=0.9, low_watermark_pct=0.3, adjust_step=4
    )
    result = asyncio.run(scaler.tick())
    assert result["db"] == 14  # 10 + 4


def test_bulkhead_scaler_low_watermark_decreases() -> None:
    """При utilization ≤ LW max_concurrent уменьшается, но не ниже min."""
    registry = BulkheadRegistry()

    async def _setup() -> None:
        await registry.get_or_create("api", max_concurrent=20)
        # 0% utilization (никто не держит слот).

    asyncio.run(_setup())

    scaler = BulkheadScaler(
        registry,
        high_watermark_pct=0.9,
        low_watermark_pct=0.3,
        adjust_step=4,
        min_capacity=8,
    )
    result = asyncio.run(scaler.tick())
    assert result["api"] == 16  # 20 - 4


def test_bulkhead_scaler_respects_min() -> None:
    """Scale-down не опускается ниже min_capacity."""
    registry = BulkheadRegistry()
    asyncio.run(registry.get_or_create("x", max_concurrent=5))
    scaler = BulkheadScaler(
        registry, adjust_step=10, min_capacity=4, low_watermark_pct=0.3
    )
    result = asyncio.run(scaler.tick())
    assert result["x"] == 4


def test_utilization_zero_for_uninit_sem() -> None:
    """Если _sem ещё None → utilization=0."""
    bh = Bulkhead(name="x", max_concurrent=10)
    assert _utilization(bh) == 0.0


# ── LocalProcessScaler ──


def test_local_process_scaler_noop_without_pidfile(tmp_path: object) -> None:
    """Без pid-файла scale_up/scale_down возвращают False."""
    scaler = LocalProcessScaler(master_pid_file=f"{tmp_path}/nonexistent.pid")
    assert scaler.scale_up() is False
    assert scaler.scale_down() is False


def test_local_process_scaler_sigusr1_called(tmp_path) -> None:
    """С валидным pid-файлом scale_up отправляет SIGUSR1."""
    pid_file = tmp_path / "master.pid"
    pid_file.write_text("12345")
    scaler = LocalProcessScaler(master_pid_file=str(pid_file))
    with patch("os.kill") as mock_kill:
        result = scaler.scale_up(by=2)
    assert result is True
    assert mock_kill.call_count == 2
    mock_kill.assert_any_call(12345, signal.SIGUSR1)


def test_local_process_scaler_sigusr2_on_scale_down(tmp_path) -> None:
    """scale_down отправляет SIGUSR2."""
    pid_file = tmp_path / "master.pid"
    pid_file.write_text("99")
    scaler = LocalProcessScaler(master_pid_file=str(pid_file))
    with patch("os.kill") as mock_kill:
        scaler.scale_down(by=1)
    mock_kill.assert_called_once_with(99, signal.SIGUSR2)


def test_local_process_scaler_invalid_args_raises() -> None:
    """Некорректные min/max workers → ValueError."""
    with pytest.raises(ValueError):
        LocalProcessScaler(min_workers=0)
    with pytest.raises(ValueError):
        LocalProcessScaler(min_workers=5, max_workers=2)


# ── AutoScaler ──


def test_auto_scaler_tick_once_aggregates() -> None:
    """tick_once собирает результаты всех компонентов."""
    registry = BulkheadRegistry()
    asyncio.run(registry.get_or_create("a", max_concurrent=10))
    bh_scaler = BulkheadScaler(registry)
    hpa = MagicMock()
    hpa.export = MagicMock()
    scaler = AutoScaler(bulkhead_scaler=bh_scaler, hpa_exporter=hpa)

    result = asyncio.run(scaler.tick_once())
    assert "a" in result["bulkhead"]
    assert result["hpa_exported"] is True
    hpa.export.assert_called_once()


def test_auto_scaler_none_components_skipped() -> None:
    """tick_once с None-компонентами не падает."""
    scaler = AutoScaler()
    result = asyncio.run(scaler.tick_once())
    assert result == {"bulkhead": {}, "process_workers": None, "hpa_exported": False}


def test_auto_scaler_start_stop_lifecycle() -> None:
    """start() создаёт task, stop() корректно отменяет."""
    scaler = AutoScaler(tick_interval_s=0.05)

    async def _run() -> bool:
        await scaler.start()
        assert scaler._task is not None
        assert not scaler._task.done()
        await asyncio.sleep(0.12)  # 2 тика
        await scaler.stop()
        return scaler._task is None

    assert asyncio.run(_run()) is True


def test_auto_scaler_invalid_interval_raises() -> None:
    """tick_interval_s ≤ 0 → ValueError."""
    with pytest.raises(ValueError):
        AutoScaler(tick_interval_s=0.0)
