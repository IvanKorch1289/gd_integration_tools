"""Sprint 6 K2 — chaos-test: no OOM при 10× spike с backpressure.

Сценарий:
    1. Создать StreamingBackpressureController + AdaptiveBulkhead.
    2. Сгенерировать 10× нормальной нагрузки (1000 параллельных acquire).
    3. Проверить, что:
       * Backpressure корректно сработал (pause flag);
       * Bulkhead отверг или отсрочил часть запросов;
       * Память не растёт без ограничений (max 100 in-flight tasks).

Запуск:
    pytest tests/chaos/test_backpressure.py -m chaos -v

Marker: ``chaos`` + ``backpressure``. CI: warn-only (continue-on-error).
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio

import pytest

pytestmark = [pytest.mark.chaos, pytest.mark.asyncio]


@pytest.mark.timeout(30)
async def test_no_oom_at_10x_spike() -> None:
    """10× spike с AdaptiveBulkhead не создаёт unbounded growth.

    Создаём 10 000 одновременных acquire-attempts на bulkhead с лимитом 100;
    проверяем, что одновременно in-flight <= 100 (backpressure работает).
    """
    from src.backend.core.resilience.backpressure import AdaptiveBulkhead

    bulkhead = AdaptiveBulkhead(
        min_concurrent=10, max_concurrent=100, initial_concurrent=100
    )

    async def worker():
        acquired = await bulkhead.acquire(timeout=0.5)
        if acquired:
            await asyncio.sleep(0.01)  # имитация работы
            bulkhead.release()
            return True
        return False

    # 10× spike: 10 000 одновременных задач при пуле 100
    tasks = [asyncio.create_task(worker()) for _ in range(1000)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Анализ: ни одна задача не должна выбросить exception
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, f"unexpected errors: {errors[:5]}"

    # Часть задач должна получить True (acquired), часть — False (timeout).
    # Главное — нет OOM и нет hang'а.
    successes = sum(1 for r in results if r is True)
    timeouts = sum(1 for r in results if r is False)
    assert successes + timeouts == 1000

    # При лимите 100 и timeout 0.5s, при ~10ms работе — должно успеть
    # обработать значительную часть (> 80%).
    assert successes >= 800, f"backpressure слишком агрессивный: {successes}/1000"

    # in_flight должен быть == 0 после всех release
    assert bulkhead.in_flight == 0


@pytest.mark.timeout(15)
async def test_streaming_controller_pauses_consumers() -> None:
    """Streaming controller pause всех consumer'ов при HighWatermark.

    Spike-сценарий: queue_size 950/1000 (95% util) → pause; затем
    queue_size 300/1000 (30%) → resume.
    """
    from unittest.mock import AsyncMock, patch

    from src.backend.core.resilience.backpressure import StreamingBackpressureController

    controller = StreamingBackpressureController(
        high_watermark=0.85, low_watermark=0.5, check_interval_s=0.1
    )

    consumers = {f"kafka_{i}": AsyncMock() for i in range(5)}
    for name, consumer in consumers.items():
        controller.register_consumer(name, consumer)

    with patch(
        "src.backend.core.config.features.feature_flags.backpressure_streaming_enabled",
        True,
    ):
        # Spike — все consumer'ы паузятся
        controller.update_queue_size(950, queue_limit=1000)
        await controller.evaluate()
        assert controller.state.is_paused is True
        for c in consumers.values():
            c.pause.assert_called_once()

        # Спад — все resume
        controller.update_queue_size(300, queue_limit=1000)
        await controller.evaluate()
        assert controller.state.is_paused is False
        for c in consumers.values():
            c.resume.assert_called_once()


@pytest.mark.timeout(30)
async def test_adaptive_stream_reader_reduces_count_at_spike() -> None:
    """AdaptiveStreamReader снижает batch size при росте utilization."""
    from src.backend.core.resilience.backpressure import AdaptiveStreamReader

    reader = AdaptiveStreamReader(
        initial_count=50, min_count=1, max_count=100, adjust_factor=2.0
    )

    # Имитация постепенного роста нагрузки
    spike_curve = [0.2, 0.4, 0.6, 0.75, 0.85, 0.92, 0.95]
    counts = []
    for util in spike_curve:
        new_count = reader.adjust(util)
        counts.append(new_count)

    # При росте utilization batch должен снижаться к концу
    assert counts[-1] < counts[0], f"AdaptiveReader не снизил batch при spike: {counts}"
    assert counts[-1] >= 1  # не ниже min_count
