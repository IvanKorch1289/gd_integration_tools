"""ClickHouseBulkWriter — async bulk insert с buffer+flush (Sprint 9 K2 W2).

Цель: ≥10x throughput для audit/metrics writes по сравнению с
:meth:`ClickHouseClient.insert` per-row.

Стратегия:

* Поступающие строки буферизуются в ``asyncio.Queue`` (bounded).
* Фоновый flusher задача периодически или при достижении буфера
  ``max_buffer_size`` делает single batch INSERT.
* Reflush triggers: timer (``flush_interval_seconds``) ИЛИ
  buffer-overflow (``max_buffer_size``).
* Graceful shutdown: ``aclose()`` дожидается финального flush.

Использование:

.. code-block:: python

    writer = ClickHouseBulkWriter(
        client=ch_client,
        table="audit_events",
        max_buffer_size=1000,
        flush_interval_seconds=1.0,
    )
    await writer.start()
    await writer.add({"event_type": "login", "ts": "..."})
    await writer.aclose()
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger

import asyncio

import time
from typing import Any

__all__ = ("BulkWriterStats", "ClickHouseBulkWriter")

logger = get_logger(__name__)


class BulkWriterStats:
    """Метрики writer'а (для Prometheus exporter).

    Attributes:
        rows_buffered: текущая длина буфера.
        rows_flushed: накопленное число успешно сохранённых строк.
        flush_count: число успешных flush'ей.
        flush_failures: число ошибок flush'а (попадают в DLQ).
        last_flush_at: timestamp последнего flush'а (UTC seconds).
    """

    def __init__(self) -> None:
        self.rows_buffered = 0
        self.rows_flushed = 0
        self.flush_count = 0
        self.flush_failures = 0
        self.last_flush_at: float | None = None


class ClickHouseBulkWriter:
    """Bounded-buffer bulk writer.

    Args:
        client: ClickHouse-клиент с ``insert(table, rows) -> int``.
        table: имя ClickHouse таблицы.
        max_buffer_size: размер буфера до forced flush (default 1000).
        flush_interval_seconds: timer-flush период (default 1.0s).
        queue_max_size: capacity ``asyncio.Queue`` (default 10000).
        on_failure: опц. callback при flush failure (envelope → DLQ).
    """

    def __init__(
        self,
        *,
        client: Any,
        table: str,
        max_buffer_size: int = 1000,
        flush_interval_seconds: float = 1.0,
        queue_max_size: int = 10_000,
        on_failure: Any = None,
    ) -> None:
        self._client = client
        self._table = table
        self._max_buffer_size = max_buffer_size
        self._flush_interval = flush_interval_seconds
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=queue_max_size
        )
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._on_failure = on_failure
        self.stats = BulkWriterStats()

    async def start(self) -> None:
        """Запускает фоновый flusher (idempotent)."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        from src.backend.core.utils.task_registry import get_task_registry

        self._task = get_task_registry().create_task(
            self._run(), name=f"chbulk-{self._table}"
        )

    async def add(self, row: dict[str, Any]) -> None:
        """Поставить строку в очередь. Блокирует если queue full."""
        await self._queue.put(row)
        self.stats.rows_buffered = self._queue.qsize()

    async def add_many(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            await self.add(row)

    async def flush_now(self) -> int:
        """Принудительный flush текущего буфера. Возвращает число записей."""
        return await self._drain_and_insert()

    async def aclose(self) -> None:
        """Graceful shutdown: финальный flush + остановка задачи."""
        self._stop.set()
        # финальный drain
        await self._drain_and_insert()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except TimeoutError:
                self._task.cancel()
                with _suppress_cancel():
                    await self._task
            self._task = None

    async def _run(self) -> None:
        """Фоновый цикл: timer-flush + buffer-overflow flush."""
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._flush_interval)
            except TimeoutError:
                pass  # timer triggered → flush
            await self._drain_and_insert()

    async def _drain_and_insert(self) -> int:
        """Извлечь все строки из очереди и сделать один INSERT."""
        batch: list[dict[str, Any]] = []
        while not self._queue.empty() and len(batch) < self._max_buffer_size:
            batch.append(self._queue.get_nowait())

        if not batch:
            return 0

        try:
            await self._client.insert(self._table, batch)
            self.stats.rows_flushed += len(batch)
            self.stats.flush_count += 1
            self.stats.last_flush_at = time.time()
            self.stats.rows_buffered = self._queue.qsize()
            return len(batch)
        except Exception as exc:
            self.stats.flush_failures += 1
            logger.exception(
                "clickhouse_bulk.flush_failed",
                extra={"table": self._table, "batch_size": len(batch)},
            )
            if self._on_failure is not None:
                try:
                    await self._on_failure(batch, exc)
                except Exception as _:
                    logger.exception("clickhouse_bulk.on_failure_callback_raised")
            return 0


class _suppress_cancel:
    """Context manager: подавляет :class:`asyncio.CancelledError`."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: type[BaseException] | None, *_: Any) -> bool:
        return exc_type is asyncio.CancelledError
