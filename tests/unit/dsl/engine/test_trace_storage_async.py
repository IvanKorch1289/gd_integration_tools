"""Sprint 83 W3: async non-blocking тесты для TraceStorage.

Проверяем, что sync file I/O (open/read/write) внутри ``JsonFileTraceStorage``
выполняется в executor thread, а НЕ блокирует event loop.

**Подход** (стандартный pattern для async I/O wrap):

1. Patch slow file I/O через ``time.sleep(SLEEP_S)`` внутри thread-bound call.
2. Запускаем async метод + параллельно ``asyncio.sleep(SLEEP_S)`` через gather.
3. Если event loop НЕ блокируется, общее время ≈ ``SLEEP_S``.
4. Если event loop блокируется (sync I/O напрямую), общее время ≈ ``2 * SLEEP_S``.

Дополнительно: проверяем, что I/O реально выполняется в отдельном потоке
(default executor), а не в main event loop thread.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from src.backend.dsl.engine.tracer import TraceEvent
from src.backend.dsl.engine.trace_storage import (
    InMemoryTraceStorage,
    JsonFileTraceStorage,
)

# Достаточно большой интервал, чтобы flaky-timing не прошёл,
# но достаточно маленький, чтобы тест не был медленным.
SLEEP_S = 0.10
# Tolerance: параллельное выполнение должно быть явно быстрее 2*SLEEP_S.
MAX_PARALLEL_TOTAL_S = SLEEP_S * 1.7  # 170ms при SLEEP_S=100ms


def _make_event(route_id: str = "r1", name: str = "p1") -> TraceEvent:
    """Создать TraceEvent с дефолтами для теста."""
    return TraceEvent(
        route_id=route_id,
        processor_name=name,
        processor_type="http",
        phase="end",
        duration_ms=1.0,
    )


def _make_slow_path_open(  # type: ignore[no-untyped-def]
    sleep_s: float, real_open: Any
):
    """Build a Path.open replacement that sleeps before delegating."""

    def slow_open(path_self: Path, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        time.sleep(sleep_s)
        return real_open(path_self, *args, **kwargs)

    return slow_open


class TestJsonFileTraceStorageNonBlocking:
    """``JsonFileTraceStorage.append`` и ``read_recent`` не должны блокировать loop."""

    @pytest.mark.asyncio
    async def test_append_does_not_block_event_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``append`` offload-ит file write в executor thread."""
        storage = JsonFileTraceStorage(tmp_path)
        event = _make_event()

        real_open = Path.open
        monkeypatch.setattr(Path, "open", _make_slow_path_open(SLEEP_S, real_open))

        start = time.monotonic()
        await asyncio.gather(
            storage.append(event),
            asyncio.sleep(SLEEP_S),  # parallel loop-friendly task
        )
        elapsed = time.monotonic() - start

        # Если event loop блокируется, elapsed >= 2 * SLEEP_S.
        # Если I/O offloaded, elapsed < MAX_PARALLEL_TOTAL_S.
        assert elapsed < MAX_PARALLEL_TOTAL_S, (
            f"append заблокировал event loop: elapsed={elapsed:.3f}s "
            f"(expected < {MAX_PARALLEL_TOTAL_S:.3f}s)"
        )

    @pytest.mark.asyncio
    async def test_read_recent_does_not_block_event_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``read_recent`` offload-ит file read в executor thread."""
        storage = JsonFileTraceStorage(tmp_path)
        event = _make_event()
        await storage.append(event)  # write без patch

        real_open = Path.open
        monkeypatch.setattr(Path, "open", _make_slow_path_open(SLEEP_S, real_open))

        start = time.monotonic()
        await asyncio.gather(
            storage.read_recent("r1", 10),
            asyncio.sleep(SLEEP_S),
        )
        elapsed = time.monotonic() - start

        assert elapsed < MAX_PARALLEL_TOTAL_S, (
            f"read_recent заблокировал event loop: elapsed={elapsed:.3f}s"
        )

    @pytest.mark.asyncio
    async def test_append_runs_in_separate_thread(self, tmp_path: Path) -> None:
        """``append`` запускает file I/O в потоке, отличном от event loop thread."""
        storage = JsonFileTraceStorage(tmp_path)
        event = _make_event()

        main_thread = threading.get_ident()
        io_thread_holder: list[int] = []

        real_open = Path.open

        def capturing_open(path_self: Path, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
            io_thread_holder.append(threading.get_ident())
            return real_open(path_self, *args, **kwargs)

        original_open = Path.open
        Path.open = capturing_open  # type: ignore[method-assign]
        try:
            await storage.append(event)
        finally:
            Path.open = original_open  # type: ignore[method-assign]

        assert io_thread_holder, "Path.open не был вызван"
        assert io_thread_holder[0] != main_thread, (
            f"file I/O выполнен в main event loop thread "
            f"(thread={io_thread_holder[0]}, main={main_thread})"
        )

    @pytest.mark.asyncio
    async def test_read_recent_runs_in_separate_thread(self, tmp_path: Path) -> None:
        """``read_recent`` запускает file read в executor thread."""
        storage = JsonFileTraceStorage(tmp_path)
        await storage.append(_make_event())

        main_thread = threading.get_ident()
        io_thread_holder: list[int] = []

        real_open = Path.open

        def capturing_open(path_self: Path, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
            io_thread_holder.append(threading.get_ident())
            return real_open(path_self, *args, **kwargs)

        original_open = Path.open
        Path.open = capturing_open  # type: ignore[method-assign]
        try:
            await storage.read_recent("r1", 10)
        finally:
            Path.open = original_open  # type: ignore[method-assign]

        assert io_thread_holder, "Path.open не был вызван"
        assert io_thread_holder[0] != main_thread, (
            f"file I/O выполнен в main event loop thread "
            f"(thread={io_thread_holder[0]}, main={main_thread})"
        )


class TestInMemoryTraceStorage:
    """``InMemoryTraceStorage`` — sync ops, но async API для uniform interface."""

    @pytest.mark.asyncio
    async def test_inmemory_append_and_read(self) -> None:
        """In-memory: append/read_recent работают корректно."""
        storage = InMemoryTraceStorage()
        for i in range(10):
            await storage.append(_make_event(name=f"p{i}"))

        recent = await storage.read_recent("r1", 100)
        assert len(recent) == 10
        assert recent[0].processor_name == "p0"
        assert recent[-1].processor_name == "p9"
