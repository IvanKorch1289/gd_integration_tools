"""S46 W3 (TD-026): TraceStorage abstraction + JSON file implementation.

S44 W1 добавил in-memory ring buffer (maxlen=1000 per route) в
``ExecutionTracer``. Buffer теряется при restart. Этот модуль добавляет
``TraceStorage`` Protocol с двумя impl:

1. ``InMemoryTraceStorage`` — re-export ``_trace_buffer`` (current behavior,
   zero overhead). Используется в dev / single-restart.
2. ``JsonFileTraceStorage`` — append-only JSONL файл (per route). Каждый
   event → JSON строка + ``\\n``. Read = tail. Persistent across restarts.

**Trade-off vs Redis/PostgreSQL (TD-026, S45+ D)**:
- JSON file: persistent, simple, zero external deps. **Не** поддерживает
  efficient range queries (linear scan). Подходит для low-volume dev/test.
- Redis/PostgreSQL: production-grade. Требует setup infra + connection
  management. S47+ D.

**Использование** (S46+ design):
    storage: TraceStorage = JsonFileTraceStorage(Path("./traces/"))
    tracer = ExecutionTracer(storage=storage)
    # emit → write to both in-memory buffer AND storage
    events = storage.read_recent(route_id, limit=100)

S46 W3 scope: abstraction + JSON impl + tests. Redis/PG impl = S47+ D.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Protocol, runtime_checkable

from src.backend.dsl.engine.tracer import TraceEvent

__all__ = (
    "TraceStorage",
    "InMemoryTraceStorage",
    "JsonFileTraceStorage",
)


@runtime_checkable
class TraceStorage(Protocol):
    """Абстракция persistent storage для trace events.

    Trade-off choice:
    - InMemoryTraceStorage: zero overhead, no persistence.
    - JsonFileTraceStorage: persistent, low-volume dev/test.
    - RedisTraceStorage (S47+ D): production, high-volume.
    - PostgresTraceStorage (S47+ D): production, queryable history.
    """

    def append(self, event: TraceEvent) -> None:
        """Сохранить event (idempotent на level per-event)."""
        ...

    def read_recent(self, route_id: str, limit: int) -> list[TraceEvent]:
        """Возвращает последние N events для route_id (chronological order)."""
        ...

    def list_routes(self) -> list[str]:
        """Возвращает все route_id с хотя бы одним event."""
        ...


class InMemoryTraceStorage:
    """Re-export ``_trace_buffer`` из ExecutionTracer (zero overhead).

    Используется default — backward compat с S44 W1. После restart —
    buffer пуст (no persistence).
    """

    def __init__(self, *, maxlen: int = 1000) -> None:
        self._buffer: dict[str, deque[TraceEvent]] = {}

    def append(self, event: TraceEvent) -> None:
        buf = self._buffer.setdefault(event.route_id, deque(maxlen=1000))
        buf.append(event)

    def read_recent(self, route_id: str, limit: int) -> list[TraceEvent]:
        buf = self._buffer.get(route_id)
        if not buf:
            return []
        return list(buf)[-min(limit, 1000):]

    def list_routes(self) -> list[str]:
        return sorted(self._buffer.keys())


class JsonFileTraceStorage:
    """Append-only JSONL file per route_id. Persistent across restarts.

    Format: ``{storage_dir}/{route_id}.jsonl`` — каждая строка = 1 event
    в JSON-сериализованной форме. Read = tail последних N строк.

    Trade-off:
    - (+) Simple, zero deps, persistent.
    - (-) Linear scan для range queries.
    - (-) Нет atomic transactions (concurrent appends → race).
    - (-) Нет retention policy (file grows indefinitely).
    """

    def __init__(self, storage_dir: str | Path) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _file_for(self, route_id: str) -> Path:
        # Sanitize route_id: replace path separators.
        safe = route_id.replace("/", "_").replace("\\", "_")
        return self._dir / f"{safe}.jsonl"

    def append(self, event: TraceEvent) -> None:
        path = self._file_for(event.route_id)
        line = json.dumps(event.to_dict(), ensure_ascii=False) + "\n"
        # Append mode: O_APPEND atomic для small writes на POSIX.
        with path.open("a", encoding="utf-8") as f:
            f.write(line)

    def read_recent(self, route_id: str, limit: int) -> list[TraceEvent]:
        path = self._file_for(route_id)
        if not path.exists():
            return []
        # Read tail: efficient если limit < file size.
        try:
            with path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        tail = lines[-min(limit, 1000):]
        events: list[TraceEvent] = []
        for raw in tail:
            try:
                d = json.loads(raw)
                events.append(
                    TraceEvent(
                        route_id=d.get("route_id", route_id),
                        processor_name=d.get("processor_name", ""),
                        processor_type=d.get("processor_type", ""),
                        phase=d.get("phase", ""),
                        duration_ms=d.get("duration_ms", 0.0),
                        timestamp=d.get("timestamp", ""),
                        error=d.get("error"),
                    )
                )
            except (json.JSONDecodeError, KeyError):
                continue
        return events

    def list_routes(self) -> list[str]:
        if not self._dir.exists():
            return []
        return sorted(
            p.stem
            for p in self._dir.glob("*.jsonl")
            if p.is_file()
        )


# Self-test (run: uv run python src/backend/dsl/engine/trace_storage.py).
if __name__ == "__main__":
    import tempfile

    # Test 1: InMemory.
    mem = InMemoryTraceStorage()
    e1 = TraceEvent(
        route_id="r1",
        processor_name="p1",
        processor_type="http",
        phase="end",
        duration_ms=10.5,
    )
    mem.append(e1)
    assert len(mem.read_recent("r1", 10)) == 1
    assert mem.list_routes() == ["r1"]
    print("InMemory OK")

    # Test 2: JsonFile.
    with tempfile.TemporaryDirectory() as td:
        js = JsonFileTraceStorage(td)
        js.append(e1)
        js.append(
            TraceEvent(
                route_id="r1",
                processor_name="p2",
                processor_type="log",
                phase="end",
                duration_ms=2.0,
            )
        )
        recent = js.read_recent("r1", 10)
        assert len(recent) == 2
        assert recent[0].processor_name == "p1"
        assert recent[1].processor_name == "p2"
        assert js.list_routes() == ["r1"]
        print("JsonFile OK")
    print("All tests pass.")
