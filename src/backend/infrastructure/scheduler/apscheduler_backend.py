"""APSchedulerBackend — реализация :class:`SchedulerBackend` поверх APScheduler.

Wave ``[wave:s18/w0-goal-driven-sweep-8-scheduler-backend-protocol]``.

Тонкий wrapper над существующим :class:`SchedulerManager` (см.
``infrastructure/scheduler/scheduler_manager.py``), который инкапсулирует
APScheduler API. Не дублирует функциональность — делегирует методам
manager'а; дополняет лишь :meth:`schedule_oneshot` / :meth:`cancel`,
которых нет на manager'е публично.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

__all__ = ("APSchedulerBackend",)


class APSchedulerBackend:
    """SchedulerBackend поверх APScheduler через :class:`SchedulerManager`.

    Args:
        manager: Опциональный экземпляр SchedulerManager. По умолчанию
            используется глобальный singleton из ``scheduler_manager``.
    """

    def __init__(self, manager: Any | None = None) -> None:
        """Инициализация: lazy-bind к глобальному SchedulerManager.

        Args:
            manager: Опциональная инстанция SchedulerManager (для тестов).
        """
        if manager is None:
            from src.backend.infrastructure.scheduler.scheduler_manager import (
                get_scheduler_manager,
            )

            manager = get_scheduler_manager()
        self._manager = manager

    async def start(self) -> None:
        """Старт планировщика."""
        await self._manager.start()

    async def stop(self) -> None:
        """Остановка планировщика."""
        await self._manager.stop()

    def schedule_cron(
        self,
        name: str,
        cron_expr: str,
        callable_ref: Any,
        *,
        timezone: str = "Europe/Moscow",
        replace_existing: bool = True,
    ) -> str:
        """Делегация в :meth:`SchedulerManager.schedule_cron`."""
        return self._manager.schedule_cron(
            name=name,
            cron_expr=cron_expr,
            callable_ref=callable_ref,
            timezone=timezone,
            replace_existing=replace_existing,
        )

    def schedule_oneshot(
        self,
        name: str,
        run_at: datetime,
        callable_ref: Any,
        *,
        replace_existing: bool = True,
    ) -> str:
        """One-shot job через :class:`DateTrigger`.

        APScheduler нативно поддерживает ``DateTrigger(run_date=...)``;
        используем его как замыкание над scheduler manager'а.
        """
        from apscheduler.triggers.date import DateTrigger

        from src.backend.core.config.settings import settings

        trigger = DateTrigger(run_date=run_at)
        job = self._manager.scheduler.add_job(
            func=callable_ref,
            trigger=trigger,
            id=name,
            name=name,
            replace_existing=replace_existing,
            jobstore=settings.scheduler.default_jobstore_name,
            executor="async",
        )
        return str(job.id)

    def cancel(self, job_id: str) -> bool:
        """Удалить job через ``remove_job``; True при успехе."""
        try:
            self._manager.scheduler.remove_job(job_id)
            return True
        except Exception:  # APScheduler JobLookupError + др.
            return False

    def list_jobs(self) -> list[dict[str, Any]]:
        """Делегация в :meth:`SchedulerManager.list_jobs`."""
        result = self._manager.list_jobs()
        return list(result)
