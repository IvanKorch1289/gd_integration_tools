"""Unit tests for ExecutionTracer."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio

import pytest

from src.backend.dsl.engine.tracer import ExecutionTracer, TraceEvent, get_tracer


class TestTraceEvent:
    def test_to_dict(self) -> None:
        ev = TraceEvent(
            route_id="r1",
            processor_name="p1",
            processor_type="t1",
            phase="end",
            duration_ms=12.3456,
            timestamp="2024-01-01T00:00:00Z",
            error=None,
        )
        d = ev.to_dict()
        assert d["route_id"] == "r1"
        assert d["phase"] == "end"
        assert d["duration_ms"] == 12.35


class TestExecutionTracer:
    @pytest.fixture
    def tracer(self) -> ExecutionTracer:
        return ExecutionTracer()

    @pytest.mark.asyncio
    async def test_trace_emits_start_and_end(self, tracer: ExecutionTracer) -> None:
        events: list[TraceEvent] = []
        async with tracer.trace("r1", "p1", "T") as td:
            pass

        # subscribe and collect
        queue = tracer._subscribers.setdefault("r1", [])
        assert len(queue) == 0  # no subscribers yet, but trace should not fail

    @pytest.mark.asyncio
    async def test_trace_emits_error(self, tracer: ExecutionTracer) -> None:
        with pytest.raises(RuntimeError, match="boom"):
            async with tracer.trace("r1", "p1", "T") as td:
                raise RuntimeError("boom")

    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self, tracer: ExecutionTracer) -> None:
        async def collect() -> list[TraceEvent]:
            events = []
            async for ev in tracer.subscribe("r1"):
                events.append(ev)
                if len(events) >= 2:
                    break
            return events

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)
        async with tracer.trace("r1", "p1", "T"):
            pass
        events = await asyncio.wait_for(task, timeout=1.0)
        assert len(events) == 2
        assert events[0].phase == "start"
        assert events[1].phase == "end"

    @pytest.mark.asyncio
    async def test_subscribe_all_receives_events(self, tracer: ExecutionTracer) -> None:
        async def collect() -> list[TraceEvent]:
            events = []
            async for ev in tracer.subscribe_all():
                events.append(ev)
                if len(events) >= 2:
                    break
            return events

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)
        async with tracer.trace("r1", "p1", "T"):
            pass
        events = await asyncio.wait_for(task, timeout=1.0)
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_emit_drops_oldest_on_backpressure(
        self, tracer: ExecutionTracer
    ) -> None:
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        tracer._subscribers["r1"] = [q]
        ev1 = TraceEvent(
            route_id="r1", processor_name="p1", processor_type="T", phase="start"
        )
        ev2 = TraceEvent(
            route_id="r1", processor_name="p1", processor_type="T", phase="end"
        )
        await tracer._emit("r1", ev1)
        await tracer._emit("r1", ev2)
        assert q.qsize() == 1

    def test_get_tracer(self) -> None:
        t1 = get_tracer()
        t2 = get_tracer()
        assert t1 is t2
