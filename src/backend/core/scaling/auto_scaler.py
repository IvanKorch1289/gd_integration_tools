"""AutoScaler — фасад над тремя уровнями автоскейлинга (Sprint 4 Wave D, V15 R-V15-10).

Объединяет:
    * Process-level через :class:`LocalProcessScaler` (Granian SIGUSR1).
    * Task-level через :class:`BulkheadScaler` (adaptive Bulkhead).
    * Container-level через :class:`K8sHpaExporter` (Prometheus metrics).

Любой компонент опционален: при ``None`` соответствующий уровень пропускается.
Фоновый цикл ``_run_loop`` периодически вызывает ``bulkhead_scaler.tick()``
и публикует метрики для HPA. Управляется через :meth:`start`/:meth:`stop`.

V15 R-V15-11 (leak prevention): asyncio.Task создаётся через
:func:`asyncio.create_task` + хранится для cancel в stop().
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger

import asyncio

from typing import Any

from src.backend.core.interfaces.observability import TemporalMetricsExporter
from src.backend.core.scaling.bulkhead_scaler import BulkheadScaler
from src.backend.core.scaling.local_process_scaler import LocalProcessScaler
from src.backend.core.utils.task_registry import get_task_registry

__all__ = ("AutoScaler",)

_logger = get_logger("core.scaling.auto_scaler")


class AutoScaler:
    """Координирующий фасад над тремя уровнями автоскейлинга.

    Args:
        process_scaler: Опц. :class:`LocalProcessScaler`. None — уровень пропущен.
        bulkhead_scaler: Опц. :class:`BulkheadScaler`. None — уровень пропущен.
        hpa_exporter: Опц. K8sHpaExporter (Prometheus metrics).
        tick_interval_s: Период `_run_loop` в секундах (default 10).
    """

    def __init__(
        self,
        *,
        process_scaler: LocalProcessScaler | None = None,
        bulkhead_scaler: BulkheadScaler | None = None,
        hpa_exporter: Any | None = None,
        tick_interval_s: float = 10.0,
    ) -> None:
        if tick_interval_s <= 0:
            raise ValueError("tick_interval_s должен быть > 0")
        self._process_scaler = process_scaler
        self._bulkhead_scaler = bulkhead_scaler
        self._hpa_exporter = hpa_exporter
        self._tick_interval_s = tick_interval_s
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Запустить фоновый tick-loop."""
        if self._task is not None and not self._task.done():
            _logger.warning("AutoScaler.start: уже запущен; пропуск")
            return
        self._stop_event.clear()
        self._task = get_task_registry().create_task(
            self._run_loop(), name="auto_scaler.loop"
        )
        _logger.info("AutoScaler started (interval=%.1fs)", self._tick_interval_s)

    async def stop(self) -> None:
        """Остановить фоновый tick-loop (graceful + cancel).

        V15 R-V15-11: гарантирует cleanup background task при shutdown.
        """
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            self._task = None
        _logger.info("AutoScaler stopped")

    async def tick_once(self) -> dict[str, Any]:
        """Однократный tick всех компонентов (для тестов и интеграции).

        Returns:
            Сводный dict ``{"bulkhead": {...}, "process_workers": int|None,
            "hpa_exported": bool}``.
        """
        result: dict[str, Any] = {
            "bulkhead": {},
            "process_workers": None,
            "hpa_exported": False,
        }
        if self._bulkhead_scaler is not None:
            result["bulkhead"] = await self._bulkhead_scaler.tick()
        if self._process_scaler is not None:
            result["process_workers"] = self._process_scaler.current_workers()
        if self._hpa_exporter is not None and hasattr(self._hpa_exporter, "export"):
            try:
                self._hpa_exporter.export()
                result["hpa_exported"] = True
            except Exception as _:
                _logger.exception("hpa_exporter.export raised; suppressed")
        return result

    async def _run_loop(self) -> None:
        """Внутренний цикл тиков."""
        try:
            while not self._stop_event.is_set():
                try:
                    await self.tick_once()
                except Exception as _:
                    _logger.exception("AutoScaler tick_once raised; продолжаем")
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._tick_interval_s
                    )
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            _logger.debug("AutoScaler._run_loop cancelled")
            raise


# ──────────────────────── Sprint 12 K2 W2: Temporal Worker Scaler ─────


class TemporalWorkerScaler:
    """Auto-scale Temporal worker pool по queue depth.

    Args:
        worker_pool: :class:`TemporalWorkerPool` или совместимый объект.
        task_queue: имя task queue для scaling.
        min_workers: минимум активных workers (default 2).
        max_workers: максимум (default 20).
        target_tasks_per_worker: 10 (см. K8s HPA target).
        cooldown_seconds: между scale events (default 30s).
    """

    def __init__(
        self,
        *,
        worker_pool: Any,
        task_queue: str = "default",
        min_workers: int = 2,
        max_workers: int = 20,
        target_tasks_per_worker: int = 10,
        cooldown_seconds: float = 30.0,
    ) -> None:
        if min_workers < 1:
            raise ValueError("min_workers >= 1")
        if max_workers < min_workers:
            raise ValueError("max_workers >= min_workers")
        if target_tasks_per_worker < 1:
            raise ValueError("target_tasks_per_worker >= 1")
        self._pool = worker_pool
        self._task_queue = task_queue
        self._min = min_workers
        self._max = max_workers
        self._target = target_tasks_per_worker
        self._cooldown = cooldown_seconds
        self._last_scale_at: float = 0.0
        self._metrics_exporter: TemporalMetricsExporter | None = None

    def _get_metrics_exporter(self) -> TemporalMetricsExporter | None:
        """Lazy-init TemporalMetricsExporter (core не импортирует infrastructure напрямую)."""
        if self._metrics_exporter is not None:
            return self._metrics_exporter
        try:
            from src.backend.infrastructure.observability.prometheus_temporal_exporter import (
                record_scale_event as _record,
            )
            from src.backend.infrastructure.observability.prometheus_temporal_exporter import (
                set_task_queue_depth as _set_depth,
            )
            from src.backend.infrastructure.observability.prometheus_temporal_exporter import (
                set_workers_active as _set_active,
            )

            class _MetricsExporter:
                """Local adapter, matching TemporalMetricsExporter."""

                def set_task_queue_depth(self, task_queue: str, depth: int) -> None:
                    _set_depth(task_queue, depth)

                def record_scale_event(self, action: str) -> None:
                    _record(action)

                def set_workers_active(self, task_queue: str, count: int) -> None:
                    _set_active(task_queue, count)

            self._metrics_exporter = _MetricsExporter()
            return self._metrics_exporter
        except ImportError:
            return None

    async def tick(self) -> dict[str, Any]:
        """Один цикл оценки: queue depth → желаемое число workers."""
        import time

        try:
            depths: dict[str, int] = await self._pool.get_queue_depth()
        except Exception as exc:
            _logger.warning("TemporalWorkerScaler.get_queue_depth failed: %s", exc)
            return {"action": "skip", "reason": str(exc)}

        depth = int(depths.get(self._task_queue, 0))

        exporter = self._get_metrics_exporter()
        if exporter:
            exporter.set_task_queue_depth(self._task_queue, depth)

        current = self._pool_current_workers()
        desired = max(
            self._min, min(self._max, -(-depth // self._target) if depth else self._min)
        )

        if desired == current:
            return {"action": "noop", "depth": depth, "workers": current}

        now = time.monotonic()
        if now - self._last_scale_at < self._cooldown:
            return {
                "action": "cooldown",
                "depth": depth,
                "workers": current,
                "desired": desired,
            }

        self._last_scale_at = now
        exporter = self._get_metrics_exporter()

        if desired > current:
            for _ in range(desired - current):
                await self._safe_start_worker()
            if exporter:
                exporter.record_scale_event("up")
        else:
            for _ in range(current - desired):
                await self._safe_stop_worker()
            if exporter:
                exporter.record_scale_event("down")

        new_count = self._pool_current_workers()
        if exporter:
            exporter.set_workers_active(self._task_queue, new_count)
        return {
            "action": "up" if desired > current else "down",
            "depth": depth,
            "from_workers": current,
            "to_workers": new_count,
        }

    def _pool_current_workers(self) -> int:
        getter = getattr(self._pool, "current_workers", None)
        if callable(getter):
            return int(getter())
        return 0

    async def _safe_start_worker(self) -> None:
        starter = getattr(self._pool, "start_worker", None)
        if callable(starter):
            try:
                result = starter(task_queue=self._task_queue)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                _logger.debug("AutoScaler: starter failed: %s", exc)

    async def _safe_stop_worker(self) -> None:
        stopper = getattr(self._pool, "stop_worker", None)
        if callable(stopper):
            try:
                result = stopper(task_queue=self._task_queue)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                _logger.debug("AutoScaler: starter failed: %s", exc)
