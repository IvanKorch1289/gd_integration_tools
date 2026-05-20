"""Sprint 14 K2 W1 — per-plugin resource monitor для Prometheus.

Назначение:
    Периодически (interval=30s по default) снимает CPU/RSS-метрики
    через psutil + tracemalloc snapshot и экспортирует их через
    Prometheus-метрики `gd_plugin_cpu_percent{plugin}`,
    `gd_plugin_rss_bytes{plugin}`, `gd_plugin_rps{plugin}`.

    Запускается из ``lifespan``-фазы через
    :class:`TaskRegistry.create_task` (R-V15-11 leak prevention) с
    deadline-эскалацией. На shutdown задача отменяется автоматически.

    Поскольку плагины in-tree (один процесс) — psutil не различает их
    CPU/RSS на уровне OS. Мониторинг компенсирует это:

    * **CPU**: tracemalloc-based traceback на стек плагина — снимок
      live-объектов с фильтром по ``extensions/<plugin>``;
    * **RPS**: counter обновляется снаружи (см. ActionHandlerRegistry,
      RouteEngine) через :meth:`record_action`.

Использование:
    monitor = PluginResourceMonitor(plugins=["credit_pipeline", ...])
    task_registry.create_task(
        monitor.run(interval_seconds=30),
        name="plugin-resource-monitor",
        deadline_seconds=None,  # бесконечный loop
    )
    # извне:
    monitor.record_action("credit_pipeline")  # инкрементирует RPS

feature_flag: ``plugin_resource_monitor_enabled`` (default-OFF до
приёмки tracemalloc-overhead на проде).
"""

from __future__ import annotations

import asyncio
import logging
import tracemalloc
from collections import defaultdict
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass

from prometheus_client import Counter, Gauge

__all__ = (
    "PluginResourceMetrics",
    "PluginResourceMonitor",
)

_logger = logging.getLogger("infrastructure.observability.plugin_resource_monitor")

# ── Prometheus метрики (создаются ленниво) ───────────────────────────

_CPU_GAUGE = Gauge(
    "gd_plugin_cpu_percent",
    "Per-plugin CPU usage estimate (process-wide CPU% scaled by plugin frame count).",
    labelnames=("plugin",),
)

_RSS_GAUGE = Gauge(
    "gd_plugin_rss_bytes",
    "Per-plugin RSS bytes estimate (tracemalloc allocations filtered by extensions/<plugin>).",
    labelnames=("plugin",),
)

_RPS_COUNTER = Counter(
    "gd_plugin_rps",
    "Per-plugin requests counter — incremented by ActionHandlerRegistry/RouteEngine.",
    labelnames=("plugin",),
)


@dataclass(slots=True)
class PluginResourceMetrics:
    """Снимок per-plugin метрик в одной выборке."""

    plugin: str
    cpu_percent: float = 0.0
    rss_bytes: int = 0
    requests_total: int = 0


@dataclass(slots=True)
class _RequestCounter:
    """Inner counter — отделяет логику инкремента от внешнего API."""

    total: int = 0


class PluginResourceMonitor:
    """Периодический snapshot per-plugin метрик.

    Args:
        plugins: Кортеж имён плагинов, которые мониторим. Пустой
            кортеж — отключает loop (NoOp).
        interval_seconds: Период сэмплирования (default 30s).
    """

    def __init__(
        self,
        plugins: Iterable[str] = (),
        *,
        interval_seconds: float = 30.0,
    ) -> None:
        self._plugins = tuple(plugins)
        self._interval = interval_seconds
        self._counters: dict[str, _RequestCounter] = defaultdict(_RequestCounter)
        self._tracemalloc_enabled = False
        self._stopped = asyncio.Event()

    # ── Public API ─────────────────────────────────────────────────

    def record_action(self, plugin: str) -> None:
        """Инкрементировать RPS counter — вызывается из ActionRegistry."""
        if plugin not in self._counters and plugin in self._plugins:
            self._counters[plugin] = _RequestCounter()
        if plugin in self._counters:
            self._counters[plugin].total += 1
            with suppress(Exception):
                _RPS_COUNTER.labels(plugin=plugin).inc()

    def snapshot(self) -> list[PluginResourceMetrics]:
        """Снять текущие метрики синхронно (для тестов / debug)."""
        results: list[PluginResourceMetrics] = []
        cpu_share = self._collect_cpu_share()
        rss_share = self._collect_rss_share()
        for plugin in self._plugins:
            metrics = PluginResourceMetrics(
                plugin=plugin,
                cpu_percent=cpu_share.get(plugin, 0.0),
                rss_bytes=rss_share.get(plugin, 0),
                requests_total=self._counters[plugin].total,
            )
            self._export(metrics)
            results.append(metrics)
        return results

    async def run(self, *, interval_seconds: float | None = None) -> None:
        """Бесконечный loop сэмплирования (под :class:`TaskRegistry`)."""
        if not self._plugins:
            return
        if interval_seconds is not None:
            self._interval = interval_seconds
        self._ensure_tracemalloc()
        while not self._stopped.is_set():
            try:
                self.snapshot()
            except Exception:  # noqa: BLE001
                _logger.exception("plugin_resource_monitor: snapshot failed")
            try:
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=self._interval
                )
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        """Запрос на graceful остановку run-loop'a."""
        self._stopped.set()

    # ── internals ──────────────────────────────────────────────────

    def _ensure_tracemalloc(self) -> None:
        """Включить tracemalloc если ещё не включён."""
        if not tracemalloc.is_tracing() and not self._tracemalloc_enabled:
            tracemalloc.start(10)  # глубина traceback'а
            self._tracemalloc_enabled = True

    @staticmethod
    def _process_cpu_percent() -> float:
        """Безопасное чтение процессорного использования через psutil."""
        try:
            import psutil  # noqa: PLC0415

            return float(psutil.Process().cpu_percent(interval=None))
        except Exception:  # noqa: BLE001
            return 0.0

    def _collect_cpu_share(self) -> dict[str, float]:
        """Грубая аппроксимация per-plugin CPU%.

        Алгоритм: считаем "стек-фреймы" через `sys._current_frames` и
        делим CPU процесса пропорционально количеству фреймов,
        идентифицированных как ``extensions/<plugin>``.
        """
        import sys  # noqa: PLC0415

        try:
            frames = sys._current_frames()  # noqa: SLF001
        except Exception:  # noqa: BLE001
            return {}

        counts: dict[str, int] = defaultdict(int)
        total = 0
        for frame in frames.values():
            f = frame
            while f is not None:
                code = f.f_code.co_filename
                for plugin in self._plugins:
                    if f"/extensions/{plugin}/" in code:
                        counts[plugin] += 1
                        total += 1
                        break
                f = f.f_back

        if total == 0:
            return dict.fromkeys(self._plugins, 0.0)
        process_cpu = self._process_cpu_percent()
        return {plugin: (counts[plugin] / total) * process_cpu for plugin in self._plugins}

    def _collect_rss_share(self) -> dict[str, int]:
        """Tracemalloc snapshot с фильтром по path extension'а."""
        if not tracemalloc.is_tracing():
            return dict.fromkeys(self._plugins, 0)
        try:
            snapshot = tracemalloc.take_snapshot()
        except Exception:  # noqa: BLE001
            return dict.fromkeys(self._plugins, 0)
        per_plugin: dict[str, int] = dict.fromkeys(self._plugins, 0)
        for stat in snapshot.statistics("filename"):
            filename = stat.traceback[0].filename if stat.traceback else ""
            for plugin in self._plugins:
                if f"/extensions/{plugin}/" in filename:
                    per_plugin[plugin] += int(stat.size)
                    break
        return per_plugin

    @staticmethod
    def _export(metrics: PluginResourceMetrics) -> None:
        """Записать gauge-метрики в Prometheus реестр."""
        with suppress(Exception):
            _CPU_GAUGE.labels(plugin=metrics.plugin).set(metrics.cpu_percent)
            _RSS_GAUGE.labels(plugin=metrics.plugin).set(metrics.rss_bytes)
