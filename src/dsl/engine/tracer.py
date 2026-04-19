"""DSL Execution Tracer — захватывает timeline процессоров.

Записывает timing и статус каждого процессора при выполнении
маршрута. Поддерживает SSE-подписку для dashboard.

Использование в ExecutionEngine:
    tracer = get_tracer()
    async with tracer.trace(route_id, processor.name, type(processor).__name__):
        await processor.process(exchange, context)
"""

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, AsyncGenerator

__all__ = ("ExecutionTracer", "TraceEvent", "get_tracer")


@dataclass(slots=True)
class TraceEvent:
    """Одно событие трассировки."""
    route_id: str
    processor_name: str
    processor_type: str
    phase: str
    duration_ms: float = 0.0
    timestamp: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "processor_name": self.processor_name,
            "processor_type": self.processor_type,
            "phase": self.phase,
            "duration_ms": round(self.duration_ms, 2),
            "timestamp": self.timestamp,
            "error": self.error,
        }


class ExecutionTracer:
    """Захватывает timeline выполнения процессоров.

    Поддерживает два режима:
    1. Inline — записывает trace в exchange.properties["_trace"]
    2. SSE — стримит события подписчикам через asyncio.Queue
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[TraceEvent]]] = {}

    @asynccontextmanager
    async def trace(
        self,
        route_id: str,
        processor_name: str,
        processor_type: str,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Context manager: emit start/end events с timing."""
        ts = datetime.now(UTC).isoformat()

        start_event = TraceEvent(
            route_id=route_id,
            processor_name=processor_name,
            processor_type=processor_type,
            phase="start",
            timestamp=ts,
        )
        await self._emit(route_id, start_event)

        start_time = time.monotonic()
        trace_data: dict[str, Any] = {"start_time": start_time}

        try:
            yield trace_data
        except Exception as exc:
            duration = (time.monotonic() - start_time) * 1000
            error_event = TraceEvent(
                route_id=route_id,
                processor_name=processor_name,
                processor_type=processor_type,
                phase="error",
                duration_ms=duration,
                timestamp=datetime.now(UTC).isoformat(),
                error=str(exc),
            )
            await self._emit(route_id, error_event)
            raise
        else:
            duration = (time.monotonic() - start_time) * 1000
            end_event = TraceEvent(
                route_id=route_id,
                processor_name=processor_name,
                processor_type=processor_type,
                phase="end",
                duration_ms=duration,
                timestamp=datetime.now(UTC).isoformat(),
            )
            trace_data["duration_ms"] = duration
            await self._emit(route_id, end_event)

    async def _emit(self, route_id: str, event: TraceEvent) -> None:
        """Отправляет событие подписчикам (lock-free, drop oldest при backpressure)."""
        for target in (route_id, "__all__"):
            queues = self._subscribers.get(target)
            if not queues:
                continue
            for q in queues:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()
                        q.put_nowait(event)
                    except (asyncio.QueueEmpty, asyncio.QueueFull):
                        pass

    async def subscribe(self, route_id: str) -> AsyncGenerator[TraceEvent, None]:
        """SSE-подписка на trace events конкретного маршрута."""
        queue: asyncio.Queue[TraceEvent] = asyncio.Queue(maxsize=1000)
        self._subscribers.setdefault(route_id, []).append(queue)

        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            subs = self._subscribers.get(route_id, [])
            if queue in subs:
                subs.remove(queue)
            if not subs:
                self._subscribers.pop(route_id, None)

    async def subscribe_all(self) -> AsyncGenerator[TraceEvent, None]:
        """SSE-подписка на все trace events."""
        queue: asyncio.Queue[TraceEvent] = asyncio.Queue(maxsize=5000)
        self._subscribers.setdefault("__all__", []).append(queue)

        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            subs = self._subscribers.get("__all__", [])
            if queue in subs:
                subs.remove(queue)


from app.core.di import app_state_singleton


@app_state_singleton("tracer", ExecutionTracer)
def get_tracer() -> ExecutionTracer:
    """Возвращает ExecutionTracer из app.state или lazy-init fallback."""
