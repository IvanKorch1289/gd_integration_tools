"""Wave 7.7 — async batching wrapper для :class:`SinkRouter`.

Цель: снизить overhead per-event dispatch в high-RPS сценариях. Вместо
создания task'а на каждый лог-record :class:`BatchingSinkRouter` копит
records в :class:`asyncio.Queue`, а фоновый воркер сливает их батчем
раз в ``flush_interval_ms`` либо при достижении ``batch_size``.

Поведение при shutdown:

* :meth:`aclose` дренирует очередь до флага `_closed`, ждёт worker'а,
  и затем закрывает inner router (`flush + close` каждого sink'а).

Совместимость:

* Реализует тот же контракт ``async dispatch(record)`` + ``async aclose()``,
  что и :class:`SinkRouter` — :func:`route_to_sinks` работает без правок.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.infrastructure.logging.router import SinkRouter

__all__ = ("BatchingSinkRouter",)

_INTERNAL_LOG = logging.getLogger("logging.batching_router")


class BatchingSinkRouter:
    """Async-batching декоратор поверх :class:`SinkRouter`.

    Args:
        inner: Исходный :class:`SinkRouter` с реальными sink-ами.
        batch_size: Максимальный размер пачки (flush раньше interval-flush'а
            если очередь набралась).
        flush_interval_ms: Период принудительного flush'а в миллисекундах.
        queue_maxsize: Лимит очереди (защита от unbounded memory growth).
            При переполнении новые records отбрасываются с warning'ом
            (не блокируем логгер).
    """

    def __init__(
        self,
        inner: SinkRouter,
        *,
        batch_size: int = 100,
        flush_interval_ms: int = 200,
        queue_maxsize: int = 10_000,
    ) -> None:
        """Сохраняет параметры; worker запускается лениво в первом dispatch."""
        self._inner = inner
        self._batch_size = max(1, batch_size)
        self._flush_interval = max(0.001, flush_interval_ms / 1000.0)
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_maxsize)
        self._worker_task: asyncio.Task[None] | None = None
        self._closed = False
        self._dropped: int = 0

    @property
    def inner(self) -> SinkRouter:
        """Внутренний router (для тестов / композиции)."""
        return self._inner

    @property
    def dropped(self) -> int:
        """Счётчик records, отброшенных при переполнении очереди."""
        return self._dropped

    @property
    def queue_size(self) -> int:
        """Текущий размер очереди."""
        return self._queue.qsize()

    def _ensure_worker(self) -> None:
        """Запускает worker-task на первом dispatch (lazy)."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(
                self._run(), name="log-batching-worker"
            )

    async def dispatch(self, record: dict[str, Any]) -> None:
        """Помещает record в очередь (non-blocking).

        Семантика fire-and-forget: при переполнении очереди record
        отбрасывается со счётчиком — логгер не блокируется.
        """
        if self._closed:
            return
        self._ensure_worker()
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped % 1000 == 1:
                _INTERNAL_LOG.warning(
                    "log batching queue full — dropped %d records (total)",
                    self._dropped,
                )

    async def _run(self) -> None:
        """Фоновый воркер: батчит records и flush'ит в inner router."""
        try:
            while True:
                batch = await self._collect_batch()
                if batch:
                    for record in batch:
                        try:
                            await self._inner.dispatch(record)
                        except Exception:  # noqa: BLE001 — изолируем sink-сбои
                            _INTERNAL_LOG.exception("inner dispatch failed")
                if self._closed and self._queue.empty():
                    return
        except asyncio.CancelledError:
            raise

    async def _collect_batch(self) -> list[dict[str, Any]]:
        """Собирает следующий батч: ждёт первого record, добивает остаток."""
        try:
            first = await asyncio.wait_for(
                self._queue.get(), timeout=self._flush_interval
            )
        except asyncio.TimeoutError:
            return []
        batch: list[dict[str, Any]] = [first]
        while len(batch) < self._batch_size:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    async def aclose(self) -> None:
        """Graceful shutdown: дренаж очереди + close inner router."""
        self._closed = True
        if self._worker_task is not None:
            try:
                await asyncio.wait_for(self._worker_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except (asyncio.CancelledError, Exception) as exc:
                    _INTERNAL_LOG.debug("worker close error: %s", exc)
        await self._inner.aclose()
