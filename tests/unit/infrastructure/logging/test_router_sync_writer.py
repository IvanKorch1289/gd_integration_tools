"""Sync-диспатчер логов: один writer-поток вместо потока на каждый вызов.

ADR-0392 (волна 18, кластер G3 — логирование).

Дефект: ``infrastructure/logging/router.py::route_to_sinks`` в sync-контексте
создавал поток на КАЖДЫЙ log-call (``threading.Thread(...).start()``).
Проба аудита: 50 sync-вызовов → 50 потоков. В CLI/воркерах/threadpool это
истощает ресурсы процесса.

Контракт после фикса:

* записи складываются в очередь;
* их разбирает ОДИН фоновый writer-поток (``log-sink-writer``);
* переполнение очереди → drop со счётчиком (логгер не блокируется).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from src.backend.core.interfaces.log_sink import LogSink
from src.backend.infrastructure.logging.router import (
    configure_router,
    reset_router,
    route_to_sinks,
)

#: Имя единственного writer-потока.
WRITER_THREAD_NAME = "log-sink-writer"

#: Таймаут ожидания доставки всех записей (секунды).
DELIVERY_TIMEOUT = 15.0


class _RecordingSink(LogSink):
    """Sink-заглушка: складывает записи в список."""

    name = "recording"
    is_healthy = True

    def __init__(self) -> None:
        """Создать пустой список записей."""
        self.records: list[dict[str, Any]] = []

    async def write(self, record: dict[str, Any]) -> None:
        """Сохранить запись."""
        self.records.append(record)

    async def flush(self) -> None:
        """Flush не требуется."""

    async def close(self) -> None:
        """Close не требуется."""


@pytest.fixture
def recording_sink() -> _RecordingSink:
    """Настроить router на sink-заглушку."""
    sink = _RecordingSink()
    configure_router([sink])
    try:
        yield sink
    finally:
        reset_router()


@pytest.mark.unit
class TestSyncDispatchSingleWriter:
    """Sync-вызовы логов обслуживает один writer-поток."""

    def test_fifty_sync_calls_do_not_create_fifty_threads(
        self, recording_sink: _RecordingSink
    ) -> None:
        """50 sync-вызовов → 1 writer-поток, а не 50 потоков."""
        before = {thread.name for thread in threading.enumerate()}

        for index in range(50):
            route_to_sinks(None, "info", {"event": f"sync.{index}"})

        deadline = time.monotonic() + DELIVERY_TIMEOUT
        while len(recording_sink.records) < 50 and time.monotonic() < deadline:
            time.sleep(0.01)

        writers = [
            thread
            for thread in threading.enumerate()
            if thread.name == WRITER_THREAD_NAME
        ]
        assert len(writers) == 1, f"ожидался один writer-поток, найдено: {len(writers)}"

        after = {thread.name for thread in threading.enumerate()}
        new_threads = after - before
        assert len(new_threads) <= 2, f"слишком много новых потоков: {new_threads}"

    def test_all_records_are_delivered(self, recording_sink: _RecordingSink) -> None:
        """Все sync-записи доходят до sink'а (очередь не теряет записи)."""
        for index in range(50):
            route_to_sinks(None, "info", {"event": f"sync.{index}"})

        deadline = time.monotonic() + DELIVERY_TIMEOUT
        while len(recording_sink.records) < 50 and time.monotonic() < deadline:
            time.sleep(0.01)

        assert len(recording_sink.records) == 50
        assert {record["event"] for record in recording_sink.records} == {
            f"sync.{index}" for index in range(50)
        }
