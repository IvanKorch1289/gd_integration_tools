"""W14.5 — durable WatermarkStore.

Покрывает:

* :class:`MemoryWatermarkStore` — load/save round-trip и изоляция от
  внешних мутаций;
* TumblingWindow с подключённым store: ``-inf`` (advance ещё не было) не
  персистится; advance триггерит save (с дебаунсом);
* После «рестарта» (новая инстанция процессора с тем же store +
  route_id) watermark восстанавливается из store, late event
  отбрасывается.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.core.clock import FakeClock
from src.core.types.watermark import WatermarkState
from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange, Message
from src.dsl.engine.processors.streaming import TumblingWindowProcessor
from src.infrastructure.watermark.memory_store import MemoryWatermarkStore


def _make_exchange(
    body: Any, *, watermark: float | None = None, event_time: float | None = None
) -> Exchange[Any]:
    headers: dict[str, Any] = {}
    if event_time is not None:
        headers["x-event-time"] = str(event_time)
    in_msg: Message[Any] = Message(body=body, headers=headers, watermark=watermark)
    return Exchange(in_message=in_msg)


class TestMemoryWatermarkStore:
    @pytest.mark.asyncio
    async def test_save_load_round_trip(self) -> None:
        store = MemoryWatermarkStore()
        state = WatermarkState(current=42.0, advanced_at=100.0, late_events_total=3)
        await store.save("r1", "tumbling-window", state)
        loaded = await store.load("r1", "tumbling-window")
        assert loaded is not None
        assert loaded.current == 42.0
        assert loaded.advanced_at == 100.0
        assert loaded.late_events_total == 3

    @pytest.mark.asyncio
    async def test_load_missing_returns_none(self) -> None:
        store = MemoryWatermarkStore()
        assert await store.load("missing", "x") is None

    @pytest.mark.asyncio
    async def test_save_does_not_share_reference(self) -> None:
        store = MemoryWatermarkStore()
        state = WatermarkState(current=10.0, advanced_at=1.0)
        await store.save("r1", "p", state)
        # Внешняя мутация не должна влиять на хранилище.
        state.current = 999.0
        loaded = await store.load("r1", "p")
        assert loaded is not None
        assert loaded.current == 10.0


class TestTumblingWindowDurable:
    @pytest.mark.asyncio
    async def test_initial_minus_inf_not_persisted(self) -> None:
        store = MemoryWatermarkStore()
        proc = TumblingWindowProcessor(
            sink=lambda b: None,
            size=10,
            interval_seconds=999.0,
            clock=FakeClock(wall_start=1_000.0),
            watermark_store=store,
            route_id="r1",
        )
        # Сообщение без watermark не приводит к advance — store пустой.
        ctx = ExecutionContext(route_id="r1")
        await proc.process(_make_exchange("a"), ctx)
        assert await store.load("r1", proc.name) is None

    @pytest.mark.asyncio
    async def test_advance_persists(self) -> None:
        clock = FakeClock(wall_start=1_000.0)
        store = MemoryWatermarkStore()
        proc = TumblingWindowProcessor(
            sink=lambda b: None,
            size=10,
            interval_seconds=999.0,
            clock=clock,
            watermark_store=store,
            route_id="r1",
            persist_min_interval=0.0,
        )
        ctx = ExecutionContext(route_id="r1")
        await proc.process(_make_exchange("a", watermark=100.0, event_time=105.0), ctx)
        loaded = await store.load("r1", proc.name)
        assert loaded is not None
        assert loaded.current == 100.0

    @pytest.mark.asyncio
    async def test_restart_restores_watermark(self) -> None:
        """После рестарта новая инстанция читает watermark и дропает late."""
        clock = FakeClock(wall_start=1_000.0)
        store = MemoryWatermarkStore()
        proc1 = TumblingWindowProcessor(
            sink=lambda b: None,
            size=10,
            interval_seconds=999.0,
            clock=clock,
            watermark_store=store,
            route_id="r1",
            persist_min_interval=0.0,
        )
        ctx = ExecutionContext(route_id="r1")
        await proc1.process(_make_exchange("a", watermark=200.0, event_time=205.0), ctx)
        # «Рестарт» — новая инстанция, тот же store/route_id/name.
        proc2 = TumblingWindowProcessor(
            sink=lambda b: None,
            size=10,
            interval_seconds=999.0,
            clock=clock,
            watermark_store=store,
            route_id="r1",
            persist_min_interval=0.0,
        )
        # До первого advance state на инстанции = -inf, но при первом
        # обращении load восстанавливает 200.0; событие event_time=150 < 200
        # должно быть отмечено late.
        ex = _make_exchange("late", watermark=200.0, event_time=150.0)
        await proc2.process(ex, ctx)
        assert ex.properties.get("_late_dropped") is True
        assert proc2.watermark_state.current == 200.0
