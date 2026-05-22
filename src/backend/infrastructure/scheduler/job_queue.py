"""Очередь отложенных задач на базе APScheduler + Redis.

Предоставляет единый API для постановки задач
с отложенным выполнением (delay) или по расписанию (cron).
Интегрируется с DSL через ``TransportType.DEFERRED``.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
from uuid import uuid4

from src.backend.core.config.settings import settings

__all__ = ("JobQueue", "get_job_queue")

logger = logging.getLogger(__name__)


class JobQueue:
    """Очередь отложенных задач.

    Обёртка над APScheduler для отложенного выполнения
    функций с поддержкой delay и cron-расписания.

    Attrs:
        _scheduler: Экземпляр APScheduler (ленивая
            инициализация при первом вызове).
    """

    def __init__(self) -> None:
        self._scheduler: Any = None

    def _ensure_scheduler(self) -> Any:
        """Получает scheduler из менеджера."""
        if self._scheduler is None:
            from src.backend.infrastructure.scheduler.scheduler_manager import (
                scheduler_manager,
            )

            self._scheduler = scheduler_manager.scheduler
        return self._scheduler

    def enqueue(
        self,
        func: Callable[..., Any | Awaitable[Any]],
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        delay: float | None = None,
        cron: str | None = None,
        job_id: str | None = None,
    ) -> str:
        """Ставит задачу в очередь.

        Args:
            func: Функция для выполнения (sync или async).
            args: Позиционные аргументы.
            kwargs: Именованные аргументы.
            delay: Задержка в секундах (одноразовое).
            cron: Cron-выражение (периодическое).
            job_id: Пользовательский ID задачи.

        Returns:
            ID созданной задачи.

        Raises:
            ValueError: Если указаны оба delay и cron.
        """
        if delay is not None and cron is not None:
            raise ValueError("Нельзя указать delay и cron одновременно")

        scheduler = self._ensure_scheduler()
        final_job_id = job_id or uuid4().hex
        final_kwargs = kwargs or {}

        if cron is not None:
            from apscheduler.triggers.cron import CronTrigger

            trigger = CronTrigger.from_crontab(cron)
            scheduler.add_job(
                func,
                trigger=trigger,
                args=args,
                kwargs=final_kwargs,
                id=final_job_id,
                replace_existing=True,
                jobstore=settings.scheduler.default_jobstore_name,
            )
            logger.info("Задача %s поставлена по cron: %s", final_job_id, cron)
        elif delay is not None:
            run_date = datetime.now() + timedelta(seconds=delay)
            scheduler.add_job(
                func,
                trigger="date",
                run_date=run_date,
                args=args,
                kwargs=final_kwargs,
                id=final_job_id,
                replace_existing=True,
                jobstore=settings.scheduler.default_jobstore_name,
            )
            logger.info("Задача %s отложена на %.1f сек", final_job_id, delay)
        else:
            # Немедленное выполнение через scheduler
            scheduler.add_job(
                func,
                args=args,
                kwargs=final_kwargs,
                id=final_job_id,
                replace_existing=True,
                jobstore=settings.scheduler.backup_jobstore_name,
            )
            logger.info("Задача %s поставлена на немедленное выполнение", final_job_id)

        return final_job_id

    def cancel(self, job_id: str) -> bool:
        """Отменяет задачу.

        Args:
            job_id: ID задачи.

        Returns:
            ``True`` если задача была найдена и отменена.
        """
        scheduler = self._ensure_scheduler()
        try:
            scheduler.remove_job(job_id)
            logger.info("Задача %s отменена", job_id)
            return True
        except (KeyError, ValueError):
            return False

    def list_jobs(self) -> list[dict[str, Any]]:
        """Возвращает список запланированных задач.

        Returns:
            Список словарей с информацией о задачах.
        """
        scheduler = self._ensure_scheduler()
        jobs = scheduler.get_jobs()
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
            for job in jobs
        ]


_job_queue: JobQueue | None = None


def get_job_queue() -> JobQueue:
    """Возвращает singleton-экземпляр очереди задач."""
    global _job_queue
    if _job_queue is None:
        _job_queue = JobQueue()
    return _job_queue
