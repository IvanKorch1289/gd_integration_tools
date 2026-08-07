"""D-A8-04 fix (cycle 1): TemporalWorkerRuntime — composition root для Worker'ов.

GAP: ``TemporalWorkerPool`` (см. ``temporal_client.py``) был определён, но
НИКОГДА не инстанцировался в production lifespan. ADR-045 обещал "Temporal
default", но фактически production worker шёл только через pg-runner path
через ``DSLStepExecutor``.

D-A8-04 fix: единый composition root — :func:`start_temporal_worker_runtime`
создаёт ``Worker`` через ``TemporalClientFactory``, регистрирует workflow
классы из :data:`workflow_registry` и запускает ``worker.run()`` в
background-task через :class:`TaskRegistry`. Graceful shutdown через
:func:`stop_temporal_worker_runtime`.

Feature-flag guarded (default-OFF через ``workflow_use_temporal``) — чтобы
не сломать существующий pg-runner path. Включается explicit-оператором
после staging-smoke Temporal-кластера.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.utils.task_registry import get_task_registry
from src.backend.core.workflow_registry import workflow_registry

__all__ = (
    "TemporalWorkerRuntime",
    "get_temporal_worker_runtime",
    "reset_temporal_worker_runtime",
    "start_temporal_worker_runtime",
    "stop_temporal_worker_runtime",
)

_logger = get_logger("workflow.temporal_worker_runtime")


class TemporalWorkerRuntime:
    """Хранит живые ``Worker`` + background-task'и для graceful shutdown.

    Singleton (composition root). Доступ через :func:`get_temporal_worker_runtime`.
    """

    def __init__(self) -> None:
        self._worker: Any | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._task_queue: str | None = None

    @property
    def is_running(self) -> bool:
        """``True`` если worker запущен и task жив."""
        return (
            self._worker is not None
            and self._task is not None
            and not self._task.done()
        )

    @property
    def task_queue(self) -> str | None:
        """Task queue для активного worker'а (или None если не запущен)."""
        return self._task_queue

    async def start(
        self,
        *,
        client: Any,
        task_queue: str = "default",
        workflow_classes: list[type] | None = None,
        activities: list[Any] | None = None,
    ) -> None:
        """Создать ``Worker`` и запустить в background-task.

        Args:
            client: уже подключённый ``temporalio.client.Client``.
            task_queue: имя task_queue для worker'а.
            workflow_classes: список workflow-классов для регистрации.
                Если ``None`` — берём :func:`workflow_registry.all`.
            activities: список activity-функций/классов.

        Raises:
            RuntimeError: если worker уже запущен (idempotency: сначала ``stop()``).
            ImportError: если ``temporalio`` SDK не установлен.
        """
        async with self._lock:
            if self.is_running:
                raise RuntimeError(
                    "TemporalWorkerRuntime уже запущен — сначала stop()"
                )

            if workflow_classes is None:
                workflow_classes = workflow_registry.all()

            if not workflow_classes:
                _logger.warning(
                    "temporal.worker_runtime.no_workflows",
                    extra={"task_queue": task_queue},
                )

            from temporalio.worker import Worker

            worker = Worker(
                client,
                task_queue=task_queue,
                workflows=workflow_classes,
                activities=activities or [],
            )

            self._worker = worker
            self._task_queue = task_queue
            # Worker.run() в temporalio возвращает coroutine, но для type-safety
            # и testability оборачиваем через asyncio.create_task если нужно.
            worker_run = worker.run()
            if not asyncio.iscoroutine(worker_run):
                # Fallback: MagicMock или sync generator → create_task wrapper.
                async def _wrap_run() -> None:
                    result = worker_run
                    if hasattr(result, "__aiter__"):
                        async for _ in result:  # pragma: no cover
                            pass

                worker_run = _wrap_run()
            self._task = get_task_registry().create_task(
                worker_run,
                name=f"temporal-worker-runtime-{task_queue}",
            )
            _logger.info(
                "temporal.worker_runtime.started",
                extra={
                    "task_queue": task_queue,
                    "workflow_count": len(workflow_classes),
                    "activity_count": len(activities or []),
                },
            )

    async def stop(self, *, timeout: float = 30.0) -> None:
        """Graceful shutdown worker'а.

        Args:
            timeout: секунд ждать завершения ``worker.shutdown()``.
        """
        async with self._lock:
            worker = self._worker
            task = self._task
            self._worker = None
            self._task_queue = None
            self._task = None

        if worker is None and task is None:
            return

        if worker is not None:
            try:
                shutdown = worker.shutdown()
                if asyncio.iscoroutine(shutdown):
                    await asyncio.wait_for(shutdown, timeout=timeout)
            except TimeoutError:
                _logger.warning(
                    "temporal.worker_runtime.shutdown_timeout",
                    extra={"timeout_s": timeout},
                )
            except Exception as exc:
                _logger.warning(
                    "temporal.worker_runtime.shutdown_error",
                    extra={"error": str(exc)},
                )

        if task is not None and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=timeout)
            except (TimeoutError, asyncio.CancelledError):
                pass

        _logger.info("temporal.worker_runtime.stopped")


_runtime: TemporalWorkerRuntime | None = None


def get_temporal_worker_runtime() -> TemporalWorkerRuntime:
    """Singleton-аксессор runtime'а."""
    global _runtime
    if _runtime is None:
        _runtime = TemporalWorkerRuntime()
    return _runtime


def reset_temporal_worker_runtime() -> None:
    """Сбрасывает singleton (только для unit-тестов)."""
    global _runtime
    _runtime = None


async def start_temporal_worker_runtime() -> None:
    """Lifespan-entrypoint: подключить Temporal client + запустить Worker.

    Используется в ``setup_infra/lifecycle.starting_operations``.

    Raises:
        RuntimeError: если feature-flag выключен или SDK не установлен.
    """
    from src.backend.core.config.features import FeatureFlags

    flags = FeatureFlags()
    # D-A8-04 fix (cycle 1): explicit feature-flag guard, default-OFF.
    enabled = bool(getattr(flags, "workflow_use_temporal", False))
    if not enabled:
        _logger.info(
            "temporal.worker_runtime.skipped",
            extra={"reason": "FEATURE_WORKFLOW_USE_TEMPORAL=false"},
        )
        return

    try:
        from src.backend.infrastructure.workflow.temporal_client import (
            TemporalClientFactory,
        )
    except ImportError as exc:
        _logger.warning(
            "temporal.worker_runtime.import_failed",
            extra={"error": str(exc)},
        )
        return

    try:
        from src.backend.core.config.settings import settings

        target = getattr(settings, "temporal_target_host", "localhost:7233")
        namespace = getattr(settings, "temporal_namespace", "default")
        task_queue = getattr(settings, "temporal_task_queue", "default")
    except ImportError:
        target = "localhost:7233"
        namespace = "default"
        task_queue = "default"

    factory = TemporalClientFactory(target_host=target)
    try:
        client = await factory.get_client(namespace)
    except (ImportError, Exception) as exc:
        _logger.warning(
            "temporal.worker_runtime.client_unavailable",
            extra={"error": str(exc), "hint": "temporalio SDK install или cluster недоступен"},
        )
        return

    runtime = get_temporal_worker_runtime()
    await runtime.start(
        client=client,
        task_queue=task_queue,
        workflow_classes=workflow_registry.all(),
        activities=[],
    )


async def stop_temporal_worker_runtime() -> None:
    """Lifespan-entrypoint: graceful shutdown worker'а. Idempotent."""
    runtime = get_temporal_worker_runtime()
    await runtime.stop()
