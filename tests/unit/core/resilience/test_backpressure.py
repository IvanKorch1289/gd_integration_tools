"""Sprint 6 K2 — тесты backpressure (streaming + adaptive bulkhead)."""

# ruff: noqa: S101, SLF001

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def _patch_flag(value: bool):
    """Патчит feature-flag backpressure_streaming_enabled."""
    return patch(
        "src.backend.core.config.features.feature_flags.backpressure_streaming_enabled",
        value,
    )


# ---------------------------------------------------------------------------
# StreamingBackpressureController
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_action_when_flag_off() -> None:
    """При flag-OFF evaluate() возвращает False (no-op)."""
    from src.backend.core.resilience.backpressure import StreamingBackpressureController

    controller = StreamingBackpressureController()
    controller.update_queue_size(950, queue_limit=1000)  # 95% utilization

    with _patch_flag(False):
        result = await controller.evaluate()

    assert result is False
    assert controller.state.is_paused is False


@pytest.mark.asyncio
async def test_pause_at_high_watermark() -> None:
    """При utilization >= high_watermark — pause всех consumer'ов."""
    from src.backend.core.resilience.backpressure import StreamingBackpressureController

    controller = StreamingBackpressureController(high_watermark=0.85, low_watermark=0.5)
    consumer = AsyncMock()
    controller.register_consumer("kafka_1", consumer)
    controller.update_queue_size(900, queue_limit=1000)  # 90%

    with _patch_flag(True):
        changed = await controller.evaluate()

    assert changed is True
    assert controller.state.is_paused is True
    consumer.pause.assert_called_once()


@pytest.mark.asyncio
async def test_resume_at_low_watermark() -> None:
    """При utilization <= low_watermark — resume."""
    from src.backend.core.resilience.backpressure import StreamingBackpressureController

    controller = StreamingBackpressureController(high_watermark=0.85, low_watermark=0.5)
    consumer = AsyncMock()
    controller.register_consumer("kafka_1", consumer)

    # Сначала pause
    controller.update_queue_size(950, queue_limit=1000)
    with _patch_flag(True):
        await controller.evaluate()
    assert controller.state.is_paused is True

    # Затем resume при низкой нагрузке
    controller.update_queue_size(300, queue_limit=1000)  # 30%
    with _patch_flag(True):
        changed = await controller.evaluate()

    assert changed is True
    assert controller.state.is_paused is False
    consumer.resume.assert_called_once()


@pytest.mark.asyncio
async def test_no_flapping_between_watermarks() -> None:
    """При utilization между watermark'ами — no state change."""
    from src.backend.core.resilience.backpressure import StreamingBackpressureController

    controller = StreamingBackpressureController(high_watermark=0.85, low_watermark=0.5)
    consumer = AsyncMock()
    controller.register_consumer("k", consumer)
    controller.update_queue_size(700, queue_limit=1000)  # 70%

    with _patch_flag(True):
        changed = await controller.evaluate()

    assert changed is False
    assert controller.state.is_paused is False
    consumer.pause.assert_not_called()


# ---------------------------------------------------------------------------
# AdaptiveStreamReader
# ---------------------------------------------------------------------------


def test_adaptive_reader_increases_at_low_util() -> None:
    """При utilization <= adjust_low_threshold — увеличить count."""
    from src.backend.core.resilience.backpressure import AdaptiveStreamReader

    reader = AdaptiveStreamReader(initial_count=10, max_count=100, adjust_factor=2.0)
    new_count = reader.adjust(utilization=0.2)  # < low (0.3)
    assert new_count == 20


def test_adaptive_reader_decreases_at_high_util() -> None:
    """При utilization >= adjust_high_threshold — уменьшить count."""
    from src.backend.core.resilience.backpressure import AdaptiveStreamReader

    reader = AdaptiveStreamReader(initial_count=10, min_count=1, adjust_factor=2.0)
    new_count = reader.adjust(utilization=0.8)  # >= high (0.7)
    assert new_count == 5


def test_adaptive_reader_no_change_in_normal_range() -> None:
    """При utilization между порогами — count не меняется."""
    from src.backend.core.resilience.backpressure import AdaptiveStreamReader

    reader = AdaptiveStreamReader(initial_count=10)
    new_count = reader.adjust(utilization=0.5)  # между low (0.3) и high (0.7)
    assert new_count == 10


def test_adaptive_reader_respects_min_max() -> None:
    """Корректировка не выходит за min/max границы."""
    from src.backend.core.resilience.backpressure import AdaptiveStreamReader

    # Уже на max — не растёт
    reader = AdaptiveStreamReader(initial_count=100, max_count=100)
    assert reader.adjust(utilization=0.1) == 100

    # Уже на min — не уменьшается
    reader = AdaptiveStreamReader(initial_count=1, min_count=1)
    assert reader.adjust(utilization=0.9) == 1


# ---------------------------------------------------------------------------
# AdaptiveBulkhead
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adaptive_bulkhead_acquire_release() -> None:
    """acquire / release корректно работают с in_flight counter."""
    from src.backend.core.resilience.backpressure import AdaptiveBulkhead

    bulkhead = AdaptiveBulkhead(initial_concurrent=3)
    assert bulkhead.in_flight == 0

    acquired = await bulkhead.acquire(timeout=1.0)
    assert acquired is True
    assert bulkhead.in_flight == 1

    bulkhead.release()
    assert bulkhead.in_flight == 0


@pytest.mark.asyncio
async def test_adaptive_bulkhead_scale_up_down() -> None:
    """scale_up/scale_down меняют current_concurrent в пределах min/max."""
    from src.backend.core.resilience.backpressure import AdaptiveBulkhead

    bulkhead = AdaptiveBulkhead(
        min_concurrent=2, max_concurrent=10, initial_concurrent=5, adjust_step=2
    )

    new = bulkhead.scale_up()
    assert new == 7

    new = bulkhead.scale_up()
    assert new == 9

    new = bulkhead.scale_up()  # +2 = 11, но max=10
    assert new == 10

    new = bulkhead.scale_down()
    assert new == 8


@pytest.mark.asyncio
async def test_adaptive_bulkhead_timeout() -> None:
    """acquire с timeout возвращает False если semaphore полный."""
    from src.backend.core.resilience.backpressure import AdaptiveBulkhead

    bulkhead = AdaptiveBulkhead(min_concurrent=1, initial_concurrent=1)
    # Захватили слот
    await bulkhead.acquire(timeout=0.1)
    # Второй acquire должен timeout
    result = await bulkhead.acquire(timeout=0.05)
    assert result is False


@pytest.mark.asyncio
async def test_adaptive_bulkhead_cancel_no_leak() -> None:
    """Отмена задачи во время acquire не приводит к утечке семафора."""
    import asyncio

    from src.backend.core.resilience.backpressure import AdaptiveBulkhead

    bulkhead = AdaptiveBulkhead(min_concurrent=1, initial_concurrent=1)
    # Захватываем единственный слот
    await bulkhead.acquire()
    assert bulkhead.in_flight == 1

    async def _cancelled_acquire() -> None:
        await bulkhead.acquire(timeout=10.0)

    task = asyncio.create_task(_cancelled_acquire())
    await asyncio.sleep(0)  # Даём задаче начать acquire
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Semaphore должен остаться в консистентном состоянии:
    # in_flight не должен "поплыть" вверх.
    assert bulkhead.in_flight == 1
    # release должен корректно освободить слот.
    bulkhead.release()
    assert bulkhead.in_flight == 0
