"""Wave 7-tail smoke: BatchingSinkRouter — dispatch/drain, batch, overflow.

Стандартные smoke-проверки без реальных sink-backends. Inner router —
подкласс :class:`SinkRouter` с in-memory списком вместо реальных sink'ов.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.infrastructure.logging.batching_router import BatchingSinkRouter
from src.backend.infrastructure.logging.router import SinkRouter


class _StubInner(SinkRouter):
    """In-memory inner router: пишет в список, не имеет sink-backends."""

    def __init__(self) -> None:
        super().__init__(sinks=[])
        self.records: list[dict[str, Any]] = []
        self.closed: bool = False

    async def dispatch(self, record: dict[str, Any]) -> None:
        self.records.append(record)

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_dispatch_and_drain_single_record() -> None:
    """Один record → доезжает в inner router после aclose."""
    inner = _StubInner()
    router = BatchingSinkRouter(
        inner, batch_size=10, flush_interval_ms=20, queue_maxsize=100
    )
    await router.dispatch({"event": "hello"})
    await router.aclose()
    assert inner.records == [{"event": "hello"}]
    assert inner.closed is True


@pytest.mark.asyncio
async def test_batch_collect_drains_all_records() -> None:
    """Несколько dispatch — все доезжают через batch-flush."""
    inner = _StubInner()
    router = BatchingSinkRouter(
        inner, batch_size=4, flush_interval_ms=20, queue_maxsize=100
    )
    for i in range(7):
        await router.dispatch({"i": i})
    await router.aclose()
    assert len(inner.records) == 7
    assert {r["i"] for r in inner.records} == set(range(7))


@pytest.mark.asyncio
async def test_queue_overflow_increments_dropped_counter() -> None:
    """Переполнение очереди увеличивает счётчик dropped, не блокирует логгер."""
    inner = _StubInner()
    router = BatchingSinkRouter(
        inner, batch_size=1, flush_interval_ms=10_000, queue_maxsize=2
    )
    # Заполняем очередь до предела + 3 «избыточных» — worker сразу не успеет
    # дренировать (interval=10s), очередь должна переполниться.
    for i in range(5):
        await router.dispatch({"i": i})
    # Даём worker'у время разобрать содержимое очереди (но overflow уже
    # зафиксирован по dropped счётчику, не зависит от drain'а).
    assert router.dropped >= 1
    # Закрываем без deadlock'а
    router._closed = True
    await asyncio.wait_for(router.aclose(), timeout=2.0)
