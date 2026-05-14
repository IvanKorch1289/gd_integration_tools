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

import asyncio
import logging
from typing import Any

from src.backend.core.scaling.bulkhead_scaler import BulkheadScaler
from src.backend.core.scaling.local_process_scaler import LocalProcessScaler

__all__ = ("AutoScaler",)

_logger = logging.getLogger("core.scaling.auto_scaler")


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
        self._task = asyncio.create_task(self._run_loop(), name="auto_scaler.loop")
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
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
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
        result: dict[str, Any] = {"bulkhead": {}, "process_workers": None, "hpa_exported": False}
        if self._bulkhead_scaler is not None:
            result["bulkhead"] = await self._bulkhead_scaler.tick()
        if self._process_scaler is not None:
            result["process_workers"] = self._process_scaler.current_workers()
        if self._hpa_exporter is not None and hasattr(self._hpa_exporter, "export"):
            try:
                self._hpa_exporter.export()
                result["hpa_exported"] = True
            except Exception:  # noqa: BLE001
                _logger.exception("hpa_exporter.export raised; suppressed")
        return result

    async def _run_loop(self) -> None:
        """Внутренний цикл тиков."""
        try:
            while not self._stop_event.is_set():
                try:
                    await self.tick_once()
                except Exception:  # noqa: BLE001
                    _logger.exception("AutoScaler tick_once raised; продолжаем")
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._tick_interval_s
                    )
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            _logger.debug("AutoScaler._run_loop cancelled")
            raise
