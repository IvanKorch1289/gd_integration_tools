"""DLQ cleanup lifecycle — periodic background runner для :class:`DLQCleanupJob`.

Wire'ит :class:`DLQCleanupJob` (ClickHouse ``dlq_events`` retention cleanup,
FIX-H1-DLQ-CLEANUP) в background asyncio-задачу через
:class:`TaskRegistry`. Интервал настраивается через
:data:`dlq_cleanup_settings.interval_hours` (default 24h).

Архитектурные принципы (mirror :mod:`stuck_monitor`):

* Task registered в :class:`TaskRegistry` → graceful shutdown через
  ``TaskRegistry.shutdown_all()`` (вызывается в ``shutdown.py``).
* Никаких ``time.sleep`` — только ``asyncio.sleep``.
* Итерация никогда не валит loop: ошибки логируются (job.run() уже
  ловит per-policy exceptions, outer guard — defense-in-depth).

Использование::

    from src.backend.infrastructure.messaging.dlq.cleanup_lifecycle import (
        start_dlq_cleanup,
        stop_dlq_cleanup,
    )

    await start_dlq_cleanup(ch_client=client, interval_hours=24.0)
    # On shutdown:
    await stop_dlq_cleanup()
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.core.messaging.dlq_policy import default_policy_registry
from src.backend.core.utils.task_registry import get_task_registry
from src.backend.infrastructure.messaging.dlq.cleanup_job import DLQCleanupJob

if TYPE_CHECKING:
    from src.backend.core.messaging.dlq_policy import DLQPolicyRegistry

__all__ = (
    "DLQCleanupScheduler",
    "default_scheduler",
    "start_dlq_cleanup",
    "stop_dlq_cleanup",
)

_logger = get_logger("infrastructure.messaging.dlq.cleanup_lifecycle")


class DLQCleanupScheduler:
    """Background-цикл для periodic DLQ retention cleanup.

    Args:
        ch_client: ClickHouse client с ``async execute(sql, params=...)``.
        interval_hours: период запуска cleanup-job (default 24h).
        registry: :class:`DLQPolicyRegistry` с retention policies
            (default — built-in 3 policies: financial/analytics/operational).
        table_name: имя DLQ-таблицы в ClickHouse (default ``dlq_events``).

    """

    def __init__(
        self,
        *,
        ch_client: Any,
        interval_hours: float = 24.0,
        registry: DLQPolicyRegistry | None = None,
        table_name: str = "dlq_events",
    ) -> None:
        if interval_hours <= 0:
            raise ValueError("interval_hours должен быть > 0")
        self._interval_seconds = interval_hours * 3600.0
        self._job = DLQCleanupJob(
            ch_client=ch_client,
            registry=registry or default_policy_registry,
            table_name=table_name,
        )
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._runs_total: int = 0

    @property
    def interval_seconds(self) -> float:
        """Вернуть интервал cleanup-цикла в секундах."""
        return self._interval_seconds

    @property
    def is_running(self) -> bool:
        """Вернуть ``True`` если background-цикл активен."""
        return self._running

    @property
    def runs_total(self) -> int:
        """Вернуть общее количество выполненных cleanup-итераций."""
        return self._runs_total

    async def start(self) -> None:
        """Зарегистрировать background-task в TaskRegistry."""
        if self._running:
            return
        self._running = True
        self._task = get_task_registry().create_task(
            self._loop(), name="dlq-cleanup",
        )
        _logger.info(
            "DLQCleanupScheduler started (interval=%.1fh, table=%s)",
            self._interval_seconds / 3600.0,
            self._job._table,
        )

    async def stop(self) -> None:
        """Graceful shutdown с отменой background-task."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        _logger.info("DLQCleanupScheduler stopped")

    async def _loop(self) -> None:
        """Periodic cleanup loop — никогда не валится (ловит все исключения)."""
        while self._running:
            try:
                stats = await self._job.run()
                self._runs_total += 1
                if stats.total_deleted or stats.errors:
                    _logger.info(
                        "DLQ cleanup iteration %d: deleted=%d, errors=%d",
                        self._runs_total,
                        stats.total_deleted,
                        len(stats.errors),
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                # Defense-in-depth: DLQCleanupJob.run() уже ловит per-policy
                # errors, но outer guard гарантирует что loop никогда не умрёт.
                _logger.warning("DLQ cleanup iteration failed: %s", exc)
            await asyncio.sleep(self._interval_seconds)


#: Singleton — используется в lifecycle-хуках startup/shutdown.
default_scheduler: DLQCleanupScheduler | None = None


async def start_dlq_cleanup(
    *,
    ch_client: Any,
    interval_hours: float = 24.0,
    table_name: str = "dlq_events",
) -> None:
    """Запустить default DLQ cleanup scheduler (idempotent).

    Args:
        ch_client: ClickHouse client.
        interval_hours: период cleanup (default 24h).
        table_name: имя DLQ-таблицы (default ``dlq_events``).

    """
    global default_scheduler
    if default_scheduler is not None and default_scheduler.is_running:
        # Already running — ничего не делаем (idempotent).
        return
    default_scheduler = DLQCleanupScheduler(
        ch_client=ch_client,
        interval_hours=interval_hours,
        table_name=table_name,
    )
    await default_scheduler.start()


async def stop_dlq_cleanup() -> None:
    """Остановить default DLQ cleanup scheduler (idempotent).

    NB: основной механизм graceful shutdown — ``TaskRegistry.shutdown_all()``
    в ``shutdown.py``, который отменяет все background-задачи. Эта функция
    обеспечивает явный graceful stop (дренаж текущей итерации).
    """
    global default_scheduler
    if default_scheduler is not None and default_scheduler.is_running:
        await default_scheduler.stop()
