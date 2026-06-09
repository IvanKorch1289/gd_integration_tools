"""Stuck-pending monitor — periodic gauge updater для Prometheus (S72 W2).

Назначение:
    Периодически вызывает :func:`count_stuck_pending` из
    :mod:`infrastructure.repositories.outbox` и обновляет Prometheus
    gauge ``outbox_stuck_pending_count``. Это позволяет Grafana alert
    правилам реагировать на "застрявшие" pending-сообщения, которые
    worker не забирает (deadlock/crash/не получает CPU).

Архитектурные принципы:
    * Capability-gate не требуется (infrastructure-уровень).
    * structlog-совместимый logger.
    * default-OFF через :class:`OutboxStuckMonitorSettings.enabled`.
    * Регистрируется в :class:`TaskRegistry` для graceful shutdown
      через :func:`stop_outbox_stuck_monitor`.
    * Никаких ``time.sleep`` — только ``asyncio.sleep``.

Wave: ``[wave:s72/w2-stuck-monitor]``.

Использование::

    from src.backend.infrastructure.messaging.outbox.stuck_monitor import (
        start_outbox_stuck_monitor,
        stop_outbox_stuck_monitor,
    )

    await start_outbox_stuck_monitor(
        threshold_seconds=300,  # 5 min
        sample_interval_seconds=60,
    )
    # On shutdown:
    await stop_outbox_stuck_monitor()
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from src.backend.core.utils.task_registry import get_task_registry
from src.backend.infrastructure.logging.factory import get_logger
from src.backend.infrastructure.repositories.outbox import (
    count_stuck_pending,
    count_stuck_pending_by_transport,
)

__all__ = (
    "OutboxStuckMonitor",
    "OutboxStuckMonitorSettings",
    "default_stuck_monitor",
    "start_outbox_stuck_monitor",
    "stop_outbox_stuck_monitor",
)

_logger = get_logger("infrastructure.messaging.outbox.stuck_monitor")

#: Prometheus gauge для outbox stuck-pending count (S72 W2).
#: Optional import — graceful no-op если prometheus_client не установлен.
try:  # pragma: no cover - prometheus_client optional
    from prometheus_client import Gauge as _PromGauge

    _STUCK_PENDING_GAUGE = _PromGauge(
        "outbox_stuck_pending_count",
        "Number of pending outbox messages older than threshold_seconds "
        "(worker not picking up = stuck). S81 W2 (ND-001 step 5): per-transport "
        "breakdown via label.",
        ["transport"],
    )
except Exception as _:
    _STUCK_PENDING_GAUGE = None  # type: ignore[assignment,unused-ignore]


@dataclass(slots=True)
class OutboxStuckMonitorSettings:
    """Конфиг для :class:`OutboxStuckMonitor`.

    Attributes:
        enabled: Default-OFF. Включается через ``stuck_monitor_enabled`` flag.
        threshold_seconds: Минимальный возраст "застрявшего" сообщения.
            Default 300с (5 мин). Рекомендация: ``2 * dispatcher_poll_interval``.
        sample_interval_seconds: Как часто обновлять gauge. Default 60с.
    """

    enabled: bool = False
    threshold_seconds: int = 300
    sample_interval_seconds: int = 60


class OutboxStuckMonitor:
    """Background-цикл для periodic stuck-pending gauge updates.

    Args:
        threshold_seconds: см. :class:`OutboxStuckMonitorSettings`.
        sample_interval_seconds: см. :class:`OutboxStuckMonitorSettings`.
    """

    def __init__(
        self, *, threshold_seconds: int = 300, sample_interval_seconds: int = 60
    ) -> None:
        if threshold_seconds <= 0:
            raise ValueError("threshold_seconds должен быть > 0")
        if sample_interval_seconds <= 0:
            raise ValueError("sample_interval_seconds должен быть > 0")
        self._threshold = threshold_seconds
        self._sample_interval = sample_interval_seconds
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._last_count: int = -1
        self._samples_total: int = 0

    @property
    def threshold_seconds(self) -> int:
        return self._threshold

    @property
    def sample_interval_seconds(self) -> int:
        return self._sample_interval

    @property
    def last_count(self) -> int:
        return self._last_count

    @property
    def samples_total(self) -> int:
        return self._samples_total

    async def start(self) -> None:
        """Зарегистрировать background-task в TaskRegistry."""
        if self._running:
            return
        self._running = True
        self._task = get_task_registry().create_task(
            self._sample_loop(), name="outbox-stuck-monitor"
        )
        _logger.info(
            "OutboxStuckMonitor started (threshold=%ds, sample_interval=%ds)",
            self._threshold,
            self._sample_interval,
        )

    async def stop(self) -> None:
        """Graceful shutdown с дренажом текущей итерации."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _logger.info("OutboxStuckMonitor stopped")

    async def _sample_loop(self) -> None:
        """Periodic gauge update loop (S81 W2: per-transport)."""
        while self._running:
            try:
                await self._sample_once()
                self._samples_total += 1
            except asyncio.CancelledError:
                break
            except Exception as exc:
                # Never crash the loop. Log и continue.
                _logger.warning("OutboxStuckMonitor sample failed: %s", exc)
            await asyncio.sleep(self._sample_interval)

    async def _sample_once(self) -> None:
        """Один sample (S81 W2, ND-001 step 5): per-transport breakdown.

        Calls:
          * count_stuck_pending → aggregate gauge (label=transport='_aggregate_')
          * count_stuck_pending_by_transport → per-transport gauge

        Prometheus convention: aggregate label uses "_aggregate_" sentinel
        (not 'all' или 'total') чтобы избежать collision с реальными
        transport names.
        """
        # 1. Aggregate count (backwards compat с S72 W2 single-value gauge)
        total = await count_stuck_pending(threshold_seconds=self._threshold)
        self._last_count = total
        if _STUCK_PENDING_GAUGE is not None:
            try:
                _STUCK_PENDING_GAUGE.labels(transport="_aggregate_").set(total)
            except Exception as exc:
                _logger.debug("Aggregate gauge set failed: %s", exc)

        # 2. Per-transport breakdown (ND-001 step 5)
        try:
            by_transport = await count_stuck_pending_by_transport(
                threshold_seconds=self._threshold
            )
        except Exception as exc:
            _logger.debug("Per-transport count failed: %s", exc)
            return

        if _STUCK_PENDING_GAUGE is None:
            return
        for transport, count in by_transport.items():
            try:
                _STUCK_PENDING_GAUGE.labels(transport=transport).set(count)
            except Exception as exc:
                _logger.debug(
                    "Per-transport gauge set failed for %s: %s", transport, exc
                )


#: Default singleton — используется в lifecycle.py hooks.
default_stuck_monitor: OutboxStuckMonitor = OutboxStuckMonitor()


async def start_outbox_stuck_monitor(
    *, threshold_seconds: int = 300, sample_interval_seconds: int = 60
) -> None:
    """Запустить default stuck-monitor (idempotent)."""
    global default_stuck_monitor
    # Recreate если config changed.
    if (
        default_stuck_monitor.threshold_seconds != threshold_seconds
        or default_stuck_monitor.sample_interval_seconds != sample_interval_seconds
    ):
        default_stuck_monitor = OutboxStuckMonitor(
            threshold_seconds=threshold_seconds,
            sample_interval_seconds=sample_interval_seconds,
        )
    await default_stuck_monitor.start()


async def stop_outbox_stuck_monitor() -> None:
    """Остановить default stuck-monitor (idempotent)."""
    if default_stuck_monitor._running:
        await default_stuck_monitor.stop()
