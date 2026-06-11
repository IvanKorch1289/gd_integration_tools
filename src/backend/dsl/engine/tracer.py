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
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.backend.dsl.engine.trace_storage import (  # Sprint 47 W1 (TD-026)
    InMemoryTraceStorage,
    TraceStorage,
)

__all__ = ("ExecutionTracer", "TraceEvent", "get_tracer")

# Sprint 44 W1: in-memory ring buffer для replay API.
# Per route_id хранит maxlen=1000 последних end/error events.
# Persistent storage = TD-026 (S45+ D).
_TRACE_BUFFER_MAXLEN = 1000


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
        """Сериализация в dict для JSON API responses.

        Returns:
            JSON-safe dict с rounded duration (2 знака после запятой).
            Используется endpoint'ом ``GET /admin/dsl-routes/{id}/traces``.
        """
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

    def __init__(self, storage: TraceStorage | None = None) -> None:
        """S47 W1 (TD-026): storage param позволяет plug external storage.

        Args:
            storage: TraceStorage impl (default InMemoryTraceStorage).
                Production: pass JsonFileTraceStorage / Redis (S47+ D).
        """
        self._subscribers: dict[str, list[asyncio.Queue[TraceEvent]]] = {}
        self._storage: TraceStorage = storage or InMemoryTraceStorage()

    @asynccontextmanager
    async def trace(
        self, route_id: str, processor_name: str, processor_type: str
    ) -> AsyncGenerator[dict[str, Any]]:
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
        """Отправляет событие подписчикам (lock-free, drop oldest при backpressure).

        S44 W1: ring buffer append для end/error events.
        S47 W1 (TD-026): также append в storage (in-memory по default,
        pluggable: JsonFile / Redis / Postgres).
        """
        # S44 W1 + S47 W1: storage append для end/error events.
        if event.phase in ("end", "error"):
            await self._storage.append(event)
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
                    except asyncio.QueueEmpty, asyncio.QueueFull:
                        pass

    async def subscribe(self, route_id: str) -> AsyncGenerator[TraceEvent]:
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

    async def subscribe_all(self) -> AsyncGenerator[TraceEvent]:
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

    async def get_recent_traces(
        self, route_id: str, limit: int = 100
    ) -> list[TraceEvent]:
        """S44 W1 + S47 W1 (TD-026): возвращает последние N events.

        Args:
            route_id: ID маршрута.
            limit: Max events to return (default 100, hard cap 1000).

        Returns:
            List of TraceEvent в chronological order (oldest first).
            Empty list если route_id не встречался или storage пуст.

        Notes:
            - Backed by TraceStorage (S46 W3 abstraction).
            - InMemory: post-restart loses data.
            - JsonFile / Redis / Postgres: persistent.
            - Используется endpoint ``GET /admin/dsl-routes/{route_id}/traces``.
        """
        return await self._storage.read_recent(route_id, limit)

    def list_traced_routes(self) -> list[str]:
        """S44 W1 + S47 W1: возвращает список route_id с events в storage."""
        return self._storage.list_routes()


from src.backend.core.di import app_state_singleton


@app_state_singleton("tracer", ExecutionTracer)
def get_tracer() -> ExecutionTracer:  # type: ignore[empty-body]
    """Возвращает ExecutionTracer из app.state или lazy-init fallback."""
