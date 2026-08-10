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
        # D-AUDIT-808 fix (cycle 8): TemporalWorkerPool instance (production wire).
        # Production lifespan создаёт pool через :func:`start_temporal_worker_runtime`
        # и регистрирует worker в нём — это даёт OTel-interceptor + Worker Versioning
        # kwargs в production. Unit-тесты :func:`start` (single-client path) — не
        # используют pool, оставляя self._pool = None.
        self._pool: Any | None = None

    def bind_pool(self, pool: Any) -> None:
        """D-AUDIT-808 fix (cycle 8): привязать worker+task от :class:`TemporalWorkerPool`.

        Используется в production lifespan после :meth:`TemporalWorkerPool.register_worker`
        — копирует ссылки на worker и background-task из pool'а в runtime,
        чтобы :attr:`is_running` и :attr:`task_queue` отражали production-state.
        """
        if pool is None:
            return
        self._pool = pool
        # Берём единственный зарегистрированный worker (production — single
        # task_queue). Если зарегистрировано несколько — берём первый.
        if pool._workers:
            first_tq = next(iter(pool._workers))
            self._worker = pool._workers[first_tq]
            self._task = pool._tasks.get(first_tq)
            self._task_queue = first_tq

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
                    "TemporalWorkerRuntime уже запущен — сначала stop()",
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


async def start_temporal_worker_runtime(
    *, activities: list[Any] | None = None,
) -> None:
    """Lifespan-entrypoint: подключить Temporal client + запустить Worker.

    D-A8-03 fix (cycle 28): kw-only ``activities`` — список activity-callables,
    decorated через ActivityBridge.decorate() в composition layer (см.
    ``_start_temporal_worker_runtime_with_activities`` wrapper в
    plugins/composition/setup_infra/lifecycle.py). Если ``activities=None``
    — backward-compat: Worker стартует с activities=[] (cycle 1 поведение).

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
        from src.backend.core.config.settings import (
            settings,
        )

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

    # D-A8-03 fix (cycle 28): kw-only activities параметр.
    # Default — [] (backward-compat когда wrapper не передал activities).
    activities_to_use = activities or []

    # D-AUDIT-808 fix (cycle 8): wire TemporalWorkerPool в production lifespan.
    # Раньше (cycle 1 D-A8-04) Worker создавался напрямую через
    # :meth:`TemporalWorkerRuntime.start` (client, task_queue, workflows, activities) —
    # TemporalWorkerPool был defined but never instantiated. Этот fix
    # оборачивает production-wire через :class:`TemporalWorkerPool`, что даёт:
    #   * OTel-interceptor auto-wire (TD-013 observability);
    #   * Worker Versioning kwargs через :class:`WorkerVersioningHelper`
    #     (S171 M10 P0, D172);
    #   * единая точка для мульти-task_queue scale-out (S180 P0-4).
    # Pre-seed factory cache — чтобы :meth:`TemporalWorkerPool.register_worker`
    # использовал уже подключённый client, а не переподключался.
    try:
        from src.backend.infrastructure.workflow.temporal_client import (
            TemporalWorkerPool,
            _ClientCacheEntry,
        )
    except ImportError as exc:
        _logger.warning(
            "temporal.worker_runtime.pool_import_failed",
            extra={"error": str(exc)},
        )
        return

    import time as _time

    factory._cache[namespace] = _ClientCacheEntry(
        client=client, created_at=_time.monotonic(), last_used_at=_time.monotonic(),
    )
    pool = TemporalWorkerPool(factory=factory, namespace=namespace)
    try:
        await pool.register_worker(
            task_queue=task_queue,
            workflows=workflow_registry.all(),
            activities=activities_to_use,
        )
    except (ImportError, RuntimeError, OSError, AttributeError) as exc:
        _logger.warning(
            "temporal.worker_runtime.register_worker_failed",
            extra={"error": str(exc), "task_queue": task_queue},
        )
        return

    runtime = get_temporal_worker_runtime()
    runtime.bind_pool(pool)
    _logger.info(
        "temporal.worker_runtime.pool_wired",
        extra={
            "task_queue": task_queue,
            "namespace": namespace,
            "worker_count": len(pool.list_workers()),
        },
    )


async def stop_temporal_worker_runtime() -> None:
    """Lifespan-entrypoint: graceful shutdown worker'а. Idempotent.

    D-AUDIT-808 fix (cycle 8): также закрывает :class:`TemporalWorkerPool`
    если production-lifespan его wire'нул (через :meth:`TemporalWorkerRuntime.bind_pool`).
    Для unit-test path (single-client ``runtime.start``) ``_pool is None`` — fallback
    на ``runtime.stop()`` как раньше.
    """
    runtime = get_temporal_worker_runtime()
    pool = runtime._pool
    if pool is not None:
        try:
            await pool.shutdown()
        except (RuntimeError, OSError, AttributeError) as exc:
            _logger.warning(
                "temporal.worker_runtime.pool_shutdown_error",
                extra={"error": str(exc)},
            )
        runtime._pool = None
        # После pool.shutdown() — обнуляем runtime refs чтобы is_running=False.
        runtime._worker = None
        runtime._task = None
        runtime._task_queue = None
        return
    await runtime.stop()
