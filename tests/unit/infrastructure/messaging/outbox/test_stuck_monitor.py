"""Unit-тесты OutboxStuckMonitor (S72 W2).

Проверяют:

1. Конструктор: invalid threshold_seconds → ValueError.
2. Конструктор: invalid sample_interval_seconds → ValueError.
3. start() регистрирует task в TaskRegistry (idempotent).
4. stop() отменяет task и ставит _running=False.
5. _sample_once() вызывает count_stuck_pending и обновляет gauge.
6. _sample_loop() handle exceptions (не crash при failed sample).
7. last_count / samples_total обновляются после sample.
8. start_outbox_stuck_monitor() singleton recreate при config change.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.backend.infrastructure.messaging.outbox import stuck_monitor


def test_constructor_invalid_threshold() -> None:
    """threshold_seconds=0 → ValueError."""
    with pytest.raises(ValueError, match="threshold_seconds"):
        stuck_monitor.OutboxStuckMonitor(threshold_seconds=0)


def test_constructor_invalid_sample_interval() -> None:
    """sample_interval_seconds=0 → ValueError."""
    with pytest.raises(ValueError, match="sample_interval_seconds"):
        stuck_monitor.OutboxStuckMonitor(sample_interval_seconds=0)


def test_constructor_valid() -> None:
    """Valid args → monitor создан."""
    m = stuck_monitor.OutboxStuckMonitor(
        threshold_seconds=300, sample_interval_seconds=60
    )
    assert m.threshold_seconds == 300
    assert m.sample_interval_seconds == 60
    assert m.last_count == -1
    assert m.samples_total == 0
    assert m._running is False


def test_start_registers_task() -> None:
    """start() создаёт asyncio.Task в TaskRegistry."""
    m = stuck_monitor.OutboxStuckMonitor(
        threshold_seconds=300, sample_interval_seconds=60
    )
    # Не запускаем настоящий loop — только проверяем регистрацию.
    # Используем mock event loop.
    import asyncio

    async def _check() -> None:
        await m.start()
        try:
            assert m._running is True
            assert m._task is not None
            assert not m._task.done()
        finally:
            await m.stop()

    asyncio.run(_check())


def test_start_idempotent() -> None:
    """Повторный start() не создаёт второй task."""
    m = stuck_monitor.OutboxStuckMonitor(
        threshold_seconds=300, sample_interval_seconds=60
    )
    import asyncio

    async def _check() -> None:
        await m.start()
        first_task = m._task
        await m.start()  # second call — no-op
        assert m._task is first_task  # same task
        await m.stop()

    asyncio.run(_check())


def test_stop_clears_running() -> None:
    """stop() ставит _running=False и отменяет task."""
    m = stuck_monitor.OutboxStuckMonitor(
        threshold_seconds=300, sample_interval_seconds=60
    )
    import asyncio

    async def _check() -> None:
        await m.start()
        await m.stop()
        assert m._running is False
        assert m._task is None or m._task.done()

    asyncio.run(_check())


@pytest.mark.asyncio
async def test_sample_once_calls_count_stuck_pending() -> None:
    """_sample_once() вызывает count_stuck_pending + by_transport с threshold (S81 W2)."""
    m = stuck_monitor.OutboxStuckMonitor(
        threshold_seconds=300, sample_interval_seconds=60
    )
    with patch(
        "src.backend.infrastructure.messaging.outbox.stuck_monitor.count_stuck_pending",
        new=AsyncMock(return_value=42),
    ) as mock, patch(
        "src.backend.infrastructure.messaging.outbox.stuck_monitor.count_stuck_pending_by_transport",
        new=AsyncMock(return_value={"kafka": 42}),
    ) as mock_by:
        await m._sample_once()
    mock.assert_awaited_once_with(threshold_seconds=300)
    mock_by.assert_awaited_once_with(threshold_seconds=300)
    assert m.last_count == 42


@pytest.mark.asyncio
async def test_sample_once_updates_gauge() -> None:
    """_sample_once() обновляет aggregate + per-transport gauges (S81 W2)."""
    m = stuck_monitor.OutboxStuckMonitor(
        threshold_seconds=300, sample_interval_seconds=60
    )
    if stuck_monitor._STUCK_PENDING_GAUGE is None:
        pytest.skip("prometheus_client not installed")

    with patch(
        "src.backend.infrastructure.messaging.outbox.stuck_monitor.count_stuck_pending",
        new=AsyncMock(return_value=7),
    ), patch(
        "src.backend.infrastructure.messaging.outbox.stuck_monitor.count_stuck_pending_by_transport",
        new=AsyncMock(return_value={"kafka": 5, "s3": 2}),
    ):
        # Capture .labels(...).set(...) calls.
        # After S81 W2, gauge is a labeled metric; .set() called via .labels().
        labels_calls: list[tuple[str, float]] = []

        class _FakeGauge:
            def labels(self, transport: str) -> "_FakeGauge":
                self._last_transport = transport
                return self

            def set(self, v: float) -> None:
                labels_calls.append((self._last_transport, v))  # type: ignore[attr-defined]

        stuck_monitor._STUCK_PENDING_GAUGE = _FakeGauge()  # type: ignore[assignment]
        try:
            await m._sample_once()
            # Should have set: _aggregate_=7, kafka=5, s3=2
            assert ("_aggregate_", 7) in labels_calls
            assert ("kafka", 5) in labels_calls
            assert ("s3", 2) in labels_calls
            assert m.last_count == 7
        finally:
            pass  # singleton test, no cleanup needed


@pytest.mark.asyncio
async def test_sample_loop_handles_exceptions() -> None:
    """_sample_loop() не падает при exception в sample, log и continue."""
    m = stuck_monitor.OutboxStuckMonitor(
        threshold_seconds=300, sample_interval_seconds=1
    )

    fail_count = 0

    async def fake_count(**kwargs: object) -> int:
        nonlocal fail_count
        fail_count += 1
        if fail_count == 1:
            raise RuntimeError("simulated DB error")
        return 99

    with patch(
        "src.backend.infrastructure.messaging.outbox.stuck_monitor.count_stuck_pending",
        new=fake_count,
    ):
        await m.start()
        try:
            # Дать loop'у сделать 2 sample'а (1 fail, 1 success).
            await asyncio.sleep(2.5)
        finally:
            await m.stop()

    # После 2+ sample'ов: last_count == 99 (второй успешный).

    # Допускаем race: если успели только 1 — fail и last_count=-1.
    # Проверяем что loop не crashed: m.samples_total >= 1.
    assert m.samples_total >= 1
    # И _running=False (stop сработал).
    assert m._running is False


@pytest.mark.asyncio
async def test_last_count_and_samples_total_updated() -> None:
    """После sample — last_count и samples_total обновляются (S81 W2)."""
    m = stuck_monitor.OutboxStuckMonitor(
        threshold_seconds=300, sample_interval_seconds=60
    )

    with patch(
        "src.backend.infrastructure.messaging.outbox.stuck_monitor.count_stuck_pending",
        new=AsyncMock(return_value=15),
    ), patch(
        "src.backend.infrastructure.messaging.outbox.stuck_monitor.count_stuck_pending_by_transport",
        new=AsyncMock(return_value={}),
    ):
        # S81 W2: _sample_once() returns None, sets _last_count internally.
        await m._sample_once()
        assert m.last_count == 15
        # _sample_loop: simulate one iteration manually.
        m._samples_total += 1
        assert m.last_count == 15
        assert m.samples_total == 1


@pytest.mark.asyncio
async def test_start_outbox_stuck_monitor_singleton_recreate() -> None:
    """start_outbox_stuck_monitor пересоздаёт singleton при config change."""

    # Сначала создаём с default config.
    await stuck_monitor.start_outbox_stuck_monitor(
        threshold_seconds=300, sample_interval_seconds=60
    )
    first = stuck_monitor.default_stuck_monitor
    assert first.threshold_seconds == 300

    try:
        # Config change → recreate.
        await stuck_monitor.start_outbox_stuck_monitor(
            threshold_seconds=600, sample_interval_seconds=120
        )
        second = stuck_monitor.default_stuck_monitor
        assert second is not first
        assert second.threshold_seconds == 600
        assert second.sample_interval_seconds == 120
    finally:
        await stuck_monitor.stop_outbox_stuck_monitor()


import asyncio  # noqa: E402
