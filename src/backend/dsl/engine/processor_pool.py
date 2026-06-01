"""Processor Pool — пул процессоров для параллельного выполнения задач.

Wave [wave:g1-processor-pool]
K-ARCH-2: Processors are poolable for parallel execution.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange
    from src.backend.dsl.engine.processors.base import BaseProcessor


@dataclass
class PooledProcessor:
    """Процессор в пуле с метаданными."""

    processor: BaseProcessor
    submitted_at: float = field(default_factory=time.monotonic)
    completed_at: float | None = None
    error: str | None = None


@dataclass
class PoolMetrics:
    """Метрики пула процессоров."""

    total_submitted: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_durations_ms: float = 0.0

    @property
    def avg_duration_ms(self) -> float:
        if self.total_completed == 0:
            return 0.0
        return self.total_durations_ms / self.total_completed


class ProcessorPool:
    """Пул для управления параллельным выполнением процессоров.

    Используется ExecutionEngine для выполнения набора процессоров
    в параллельном режиме (например, для ScatterGather, Multicast,
    RecipientList).

    Args:
        max_workers: Максимальное количество параллельных воркеров.
            По умолчанию ``4``.
        thread_pool: Опциональный ThreadPoolExecutor для CPU-bound задач.
            Если не передан, создаётся внутри.
    """

    def __init__(
        self, max_workers: int = 4, thread_pool: ThreadPoolExecutor | None = None
    ) -> None:
        self._max_workers = max_workers
        self._thread_pool = thread_pool
        self._own_thread_pool: ThreadPoolExecutor | None = None
        self._metrics = PoolMetrics()
        self._active: set[asyncio.Task[Any]] = set()
        self._semaphore = asyncio.Semaphore(max_workers)

    @property
    def metrics(self) -> PoolMetrics:
        """Returns current pool metrics."""
        return self._metrics

    @property
    def max_workers(self) -> int:
        """Maximum number of parallel workers."""
        return self._max_workers

    @property
    def active_count(self) -> int:
        """Number of currently active tasks."""
        return len(self._active)

    def _get_thread_pool(self) -> ThreadPoolExecutor:
        """Lazily creates/returns the underlying thread pool."""
        if self._thread_pool is None:
            self._own_thread_pool = ThreadPoolExecutor(
                max_workers=self._max_workers, thread_name_prefix="processor_pool_"
            )
            return self._own_thread_pool
        return self._thread_pool

    async def _execute_one(
        self,
        processor: BaseProcessor,
        exchange: Exchange[Any],
        context: ExecutionContext,
        timeout: float | None = None,
    ) -> tuple[BaseProcessor, dict[str, Any]]:
        """Execute a single processor with timeout tracking."""
        start = time.monotonic()
        pooled = PooledProcessor(processor=processor)

        try:
            if asyncio.iscoroutinefunction(processor.process):
                await asyncio.wait_for(
                    processor.process(exchange, context), timeout=timeout
                )
            else:
                loop = asyncio.get_event_loop()
                await asyncio.wait_for(
                    loop.run_in_executor(
                        self._get_thread_pool(),
                        lambda: processor.process(exchange, context),
                    ),
                    timeout=timeout,
                )
            pooled.completed_at = time.monotonic()
            duration_ms = (pooled.completed_at - start) * 1000
            return processor, {
                "processor": processor.name,
                "type": type(processor).__name__,
                "duration_ms": duration_ms,
                "status": "ok",
            }
        except asyncio.TimeoutError:
            pooled.error = f"Timeout after {timeout}s"
            return processor, {
                "processor": processor.name,
                "type": type(processor).__name__,
                "duration_ms": (time.monotonic() - start) * 1000,
                "status": "error",
                "error": pooled.error,
            }
        except Exception as exc:  # noqa: BLE001
            pooled.error = str(exc)
            return processor, {
                "processor": processor.name,
                "type": type(processor).__name__,
                "duration_ms": (time.monotonic() - start) * 1000,
                "status": "error",
                "error": pooled.error,
            }

    @asynccontextmanager
    async def _tracked(self, task: asyncio.Task[Any]):
        """Track active task for graceful cancellation on shutdown."""
        self._active.add(task)
        try:
            yield task
        finally:
            self._active.discard(task)

    async def execute_parallel(
        self,
        processors: list[BaseProcessor],
        exchange: Exchange[Any],
        context: ExecutionContext,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        """Execute processors in parallel with bounded concurrency.

        Args:
            processors: List of processors to execute.
            exchange: The exchange object passed to each processor.
            context: Execution context.
            timeout: Optional timeout per processor in seconds.

        Returns:
            List of trace entries for each processor execution.
        """
        self._metrics.total_submitted += len(processors)

        async def run_with_sem(proc: BaseProcessor) -> dict[str, Any]:
            async with self._semaphore:
                _, result = await self._execute_one(proc, exchange, context, timeout)
                self._metrics.total_completed += 1
                if result["status"] == "error":
                    self._metrics.total_failed += 1
                self._metrics.total_durations_ms += result.get("duration_ms", 0)
                return result

        tasks = [run_with_sem(p) for p in processors]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        trace_entries: list[dict[str, Any]] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                trace_entries.append(
                    {
                        "processor": processors[i].name,
                        "type": type(processors[i]).__name__,
                        "duration_ms": 0.0,
                        "status": "error",
                        "error": str(result),
                    }
                )
                self._metrics.total_failed += 1
            elif isinstance(result, dict):
                trace_entries.append(result)

        return trace_entries

    async def execute_with_callback(
        self,
        processor: BaseProcessor,
        exchange: Exchange[Any],
        context: ExecutionContext,
        on_complete: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute a processor and optionally call on_complete callback.

        Args:
            processor: The processor to execute.
            exchange: The exchange object.
            context: Execution context.
            on_complete: Optional async callback invoked with trace entry on completion.
            timeout: Optional timeout in seconds.

        Returns:
            Trace entry dictionary.
        """
        _, result = await self._execute_one(processor, exchange, context, timeout)

        if on_complete is not None:
            await on_complete(result)

        return result

    async def shutdown(self, cancel_pending: bool = True) -> None:
        """Shutdown the pool and optionally cancel pending tasks.

        Args:
            cancel_pending: If True, cancel all active tasks. Otherwise, wait for them.
        """
        if cancel_pending:
            for task in self._active:
                if not task.done():
                    task.cancel()
            if self._active:
                await asyncio.gather(*self._active, return_exceptions=True)

        if self._own_thread_pool is not None:
            self._own_thread_pool.shutdown(wait=True)
            self._own_thread_pool = None

    def __repr__(self) -> str:
        return (
            f"ProcessorPool(max_workers={self._max_workers}, "
            f"active={len(self._active)}, "
            f"submitted={self._metrics.total_submitted}, "
            f"completed={self._metrics.total_completed})"
        )


# Global pool instance for convenience access
_global_pool: ProcessorPool | None = None


def get_processor_pool() -> ProcessorPool:
    """Get or create the global ProcessorPool instance.

    Thread-safe singleton pattern for the global pool.
    """
    global _global_pool
    if _global_pool is None:
        _global_pool = ProcessorPool()
    return _global_pool


def set_processor_pool(pool: ProcessorPool) -> None:
    """Set the global ProcessorPool instance (for testing or custom pools)."""
    global _global_pool
    _global_pool = pool
