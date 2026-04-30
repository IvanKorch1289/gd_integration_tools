"""W14.3 — watermarks и late events.

Покрывает:

* монотонность ``WatermarkState.advance``;
* детекция late events через ``is_late`` с ``allowed_lateness``;
* TumblingWindowProcessor: in-order vs late events vs allowed_lateness;
* применение ``LatePolicy.DROP`` / ``SIDE_OUTPUT``;
* watermark не откатывается назад при events с меньшим watermark;
* hypothesis property: монотонная последовательность advance.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.core.clock import FakeClock
from src.core.types.watermark import LatePolicy, WatermarkState
from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange, Message
from src.dsl.engine.late_event_policy import apply_late_policy
from src.dsl.engine.processors.streaming import (
    SessionWindowProcessor,
    SlidingWindowProcessor,
    TumblingWindowProcessor,
)


def _make_exchange(
    body: Any, *, watermark: float | None = None, event_time: float | None = None
) -> Exchange[Any]:
    headers: dict[str, Any] = {}
    if event_time is not None:
        headers["x-event-time"] = str(event_time)
    in_msg: Message[Any] = Message(body=body, headers=headers, watermark=watermark)
    return Exchange(in_message=in_msg)


class TestWatermarkState:
    def test_advance_monotonic(self) -> None:
        ws = WatermarkState()
        assert ws.advance(10.0, now=100.0) is True
        assert ws.advance(20.0, now=110.0) is True
        # Откат недопустим.
        assert ws.advance(15.0, now=120.0) is False
        assert ws.current == 20.0
        # Advanced_at — момент последнего успешного продвижения.
        assert ws.advanced_at == 110.0

    def test_is_late_strict(self) -> None:
        ws = WatermarkState(current=100.0)
        assert ws.is_late(99.9) is True
        assert ws.is_late(100.0) is False
        assert ws.is_late(150.0) is False

    def test_is_late_allowed_lateness(self) -> None:
        ws = WatermarkState(current=100.0)
        # Опаздывает на 5s, но allowance 10s — не late.
        assert ws.is_late(95.0, allowed_lateness=10.0) is False
        # Опаздывает на 15s, allowance 10s — late.
        assert ws.is_late(85.0, allowed_lateness=10.0) is True

    @given(
        values=st.lists(st.floats(min_value=0, max_value=1e6), min_size=1, max_size=50)
    )
    def test_advance_property_monotonic(self, values: list[float]) -> None:
        """Property: после серии advance() current == max(values)."""
        ws = WatermarkState()
        for v in values:
            ws.advance(v, now=0.0)
        assert ws.current == max(values)


class TestTumblingWindowWatermarks:
    @pytest.fixture
    def fake_clock(self) -> FakeClock:
        return FakeClock(wall_start=1_000_000.0)

    @pytest.mark.asyncio
    async def test_in_order_events_pass(self, fake_clock: FakeClock) -> None:
        captured: list[list[Any]] = []

        def sink(bucket: list[Any]) -> None:
            captured.append(bucket)

        proc = TumblingWindowProcessor(
            sink=sink, size=2, interval_seconds=999.0, clock=fake_clock
        )
        ctx = ExecutionContext(route_id="r1")

        # Watermark = 100, event_time = 105 (>= watermark, not late).
        await proc.process(_make_exchange("a", watermark=100.0, event_time=105.0), ctx)
        await proc.process(_make_exchange("b", watermark=110.0, event_time=115.0), ctx)
        # size=2 → flush
        assert captured == [["a", "b"]]

    @pytest.mark.asyncio
    async def test_late_event_dropped_by_default(self, fake_clock: FakeClock) -> None:
        captured: list[list[Any]] = []

        def sink(bucket: list[Any]) -> None:
            captured.append(bucket)

        proc = TumblingWindowProcessor(
            sink=sink, size=2, interval_seconds=999.0, clock=fake_clock
        )
        ctx = ExecutionContext(route_id="r1")

        # Установить watermark.
        await proc.process(_make_exchange("a", watermark=100.0, event_time=105.0), ctx)
        # Late: event_time=80 < watermark=100.
        ex_late = _make_exchange("late", watermark=100.0, event_time=80.0)
        await proc.process(ex_late, ctx)
        assert ex_late.properties.get("_late_dropped") is True
        assert proc.watermark_state.late_events_total == 1
        # В окне только "a", "late" дропнут.
        assert proc.watermark_state.current == 100.0

    @pytest.mark.asyncio
    async def test_late_within_allowed_lateness_passes(
        self, fake_clock: FakeClock
    ) -> None:
        captured: list[list[Any]] = []

        def sink(bucket: list[Any]) -> None:
            captured.append(bucket)

        proc = TumblingWindowProcessor(
            sink=sink,
            size=3,
            interval_seconds=999.0,
            clock=fake_clock,
            allowed_lateness_seconds=30.0,
        )
        ctx = ExecutionContext(route_id="r1")

        await proc.process(_make_exchange("a", watermark=100.0, event_time=105.0), ctx)
        # event_time=85, watermark=100 → 15s late, allowed=30s → проходит.
        ex_borderline = _make_exchange("border", watermark=100.0, event_time=85.0)
        await proc.process(ex_borderline, ctx)
        assert ex_borderline.properties.get("_late_dropped") is None

    @pytest.mark.asyncio
    async def test_late_beyond_allowed_dropped(self, fake_clock: FakeClock) -> None:
        proc = TumblingWindowProcessor(
            sink=lambda b: None,
            size=10,
            interval_seconds=999.0,
            clock=fake_clock,
            allowed_lateness_seconds=10.0,
        )
        ctx = ExecutionContext(route_id="r1")

        await proc.process(_make_exchange("a", watermark=100.0, event_time=105.0), ctx)
        # event_time=80 → 20s late, allowed=10s → дроп.
        ex = _make_exchange("late", watermark=100.0, event_time=80.0)
        await proc.process(ex, ctx)
        assert ex.properties.get("_late_dropped") is True

    @pytest.mark.asyncio
    async def test_watermark_does_not_regress(self, fake_clock: FakeClock) -> None:
        proc = TumblingWindowProcessor(
            sink=lambda b: None, size=10, interval_seconds=999.0, clock=fake_clock
        )
        ctx = ExecutionContext(route_id="r1")
        await proc.process(_make_exchange("a", watermark=200.0, event_time=205.0), ctx)
        # Сообщение с меньшим watermark не сдвигает state назад.
        await proc.process(_make_exchange("b", watermark=150.0, event_time=205.0), ctx)
        assert proc.watermark_state.current == 200.0


class TestSlidingWindowWatermarks:
    @pytest.fixture
    def fake_clock(self) -> FakeClock:
        return FakeClock(wall_start=1_000_000.0)

    @pytest.mark.asyncio
    async def test_late_event_dropped_by_default(self, fake_clock: FakeClock) -> None:
        proc = SlidingWindowProcessor(
            sink=lambda b: None,
            window_seconds=10.0,
            step_seconds=999.0,
            clock=fake_clock,
        )
        ctx = ExecutionContext(route_id="r1")

        await proc.process(_make_exchange("a", watermark=100.0, event_time=105.0), ctx)
        ex_late = _make_exchange("late", watermark=100.0, event_time=80.0)
        await proc.process(ex_late, ctx)
        assert ex_late.properties.get("_late_dropped") is True
        assert proc.watermark_state.late_events_total == 1
        # Late не должен попасть в буфер.
        assert [body for _, body in proc._buffer] == ["a"]

    @pytest.mark.asyncio
    async def test_late_within_allowed_lateness_passes(
        self, fake_clock: FakeClock
    ) -> None:
        proc = SlidingWindowProcessor(
            sink=lambda b: None,
            window_seconds=10.0,
            step_seconds=999.0,
            clock=fake_clock,
            allowed_lateness_seconds=30.0,
        )
        ctx = ExecutionContext(route_id="r1")

        await proc.process(_make_exchange("a", watermark=100.0, event_time=105.0), ctx)
        ex = _make_exchange("border", watermark=100.0, event_time=85.0)
        await proc.process(ex, ctx)
        assert ex.properties.get("_late_dropped") is None
        assert [body for _, body in proc._buffer] == ["a", "border"]

    @pytest.mark.asyncio
    async def test_watermark_does_not_regress(self, fake_clock: FakeClock) -> None:
        proc = SlidingWindowProcessor(
            sink=lambda b: None,
            window_seconds=10.0,
            step_seconds=999.0,
            clock=fake_clock,
        )
        ctx = ExecutionContext(route_id="r1")
        await proc.process(_make_exchange("a", watermark=200.0, event_time=205.0), ctx)
        await proc.process(_make_exchange("b", watermark=150.0, event_time=205.0), ctx)
        assert proc.watermark_state.current == 200.0


class TestSessionWindowWatermarks:
    @pytest.fixture
    def fake_clock(self) -> FakeClock:
        return FakeClock(wall_start=1_000_000.0)

    @pytest.mark.asyncio
    async def test_late_event_dropped_by_default(self, fake_clock: FakeClock) -> None:
        proc = SessionWindowProcessor(
            sink=lambda b: None, gap_seconds=999.0, clock=fake_clock
        )
        ctx = ExecutionContext(route_id="r1")

        await proc.process(_make_exchange("a", watermark=100.0, event_time=105.0), ctx)
        ex_late = _make_exchange("late", watermark=100.0, event_time=80.0)
        await proc.process(ex_late, ctx)
        assert ex_late.properties.get("_late_dropped") is True
        assert proc.watermark_state.late_events_total == 1
        # Late не должен попасть в session-буфер.
        assert proc._buffer == ["a"]

    @pytest.mark.asyncio
    async def test_late_within_allowed_lateness_passes(
        self, fake_clock: FakeClock
    ) -> None:
        proc = SessionWindowProcessor(
            sink=lambda b: None,
            gap_seconds=999.0,
            clock=fake_clock,
            allowed_lateness_seconds=30.0,
        )
        ctx = ExecutionContext(route_id="r1")

        await proc.process(_make_exchange("a", watermark=100.0, event_time=105.0), ctx)
        ex = _make_exchange("border", watermark=100.0, event_time=85.0)
        await proc.process(ex, ctx)
        assert ex.properties.get("_late_dropped") is None
        assert proc._buffer == ["a", "border"]

    @pytest.mark.asyncio
    async def test_watermark_does_not_regress(self, fake_clock: FakeClock) -> None:
        proc = SessionWindowProcessor(
            sink=lambda b: None, gap_seconds=999.0, clock=fake_clock
        )
        ctx = ExecutionContext(route_id="r1")
        await proc.process(_make_exchange("a", watermark=200.0, event_time=205.0), ctx)
        await proc.process(_make_exchange("b", watermark=150.0, event_time=205.0), ctx)
        assert proc.watermark_state.current == 200.0


class TestLatePolicy:
    @pytest.mark.asyncio
    async def test_drop_returns_false(self) -> None:
        ws = WatermarkState(current=100.0)
        ex = _make_exchange("x", event_time=50.0)
        keep = await apply_late_policy(ex, state=ws, policy=LatePolicy.DROP)
        assert keep is False
        assert ex.properties.get("_late_dropped") is True

    @pytest.mark.asyncio
    async def test_side_output_calls_callback(self) -> None:
        ws = WatermarkState(current=100.0)
        ex = _make_exchange("x", event_time=50.0)
        called: list[Exchange[Any]] = []

        def side(e: Exchange[Any]) -> None:
            called.append(e)

        keep = await apply_late_policy(
            ex, state=ws, policy=LatePolicy.SIDE_OUTPUT, side_output=side
        )
        assert keep is True
        assert called == [ex]
        assert ex.properties.get("_late_routed") is True

    @pytest.mark.asyncio
    async def test_reprocess_marks_exchange(self) -> None:
        ws = WatermarkState(current=100.0)
        ex = _make_exchange("x", event_time=50.0)
        keep = await apply_late_policy(ex, state=ws, policy=LatePolicy.REPROCESS)
        assert keep is True
        assert ex.properties.get("_late_reprocess") is True
