"""SchedulerFacade — capability-checked фасад для scheduler.

Provides capability-checked access to APScheduler for extensions.

W11 cycle 158+ wiring fix (v6 P3-13 regression):
    ``add_job`` переписан с реальным async orchestration:
    - cron_expr вместо trigger= + **trigger_kwargs (overload убран);
    - catchup + catchup_window_days — keyword-only, НЕ передаются в
      ``SchedulerManager.schedule_cron`` (ранее APScheduler CronTrigger
      reject'ил их как unknown kwargs);
    - ``await backfill.materialize_window(...)`` — ранее fire-and-forget
      через ``loop.create_task`` (coroutine-поля читались как
      BackfillReport, ошибки поглощались except Exception);
    - return structured dict с статусами registered, history_materialized,
      catchup_scheduled (НЕ silent best-effort);
    - capacity-check + capability audit на каждой ветке.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from datetime import timezone as _tz
from typing import Any

from src.backend.core.errors import ServiceError
from src.backend.core.logging import get_logger

__all__ = ("SchedulerFacade",)

_logger = get_logger("services.scheduler.facade")


class SchedulerFacade:
    """Capability-checked фасад для scheduler.

    Args:
        capability_check: Опц. callback ``CapabilityGate.check``.
        plugin: Имя caller'а (для capability-event и audit).
        session_factory: async_sessionmaker для run-history store (нужно
            если планируется ``catchup=True``).

    """

    def __init__(
        self,
        *,
        capability_check: Any | None = None,
        plugin: str = "extension",
        session_factory: Any | None = None,
    ) -> None:
        self._check = capability_check
        self._plugin = plugin
        self._session_factory = session_factory
        self._run_history_store: Any | None = None

    def _assert(self, action: str, resource: str) -> None:
        if self._check is not None:
            self._check(self._plugin, action, resource)

    async def add_job(
        self,
        job_id: str,
        func: Any,
        cron_expr: str,
        *,
        catchup: bool = False,
        catchup_window_days: int = 1,
        timezone: str = "Europe/Moscow",
    ) -> dict[str, Any]:
        """Добавить cron-задачу + (опционально) материализовать catchup-окно.

        Args:
            job_id: Уникальный ID задачи.
            func: Callable для выполнения.
            cron_expr: cron-строка (croniter format).
            catchup: Если True — материализовать run-history для catchup-окна
                (pending-тики будут исполнены ``run_pending``).
            catchup_window_days: Размер catchup-окна (дней; default=1).
            timezone: IANA timezone для cron.

        Returns:
            dict с статусами:

            ::

                {
                    "job_id": str,                # registered job id
                    "registered": bool,            # APScheduler registration OK
                    "history_materialized": bool,  # catchup-материализация OK
                    "catchup_scheduled": bool,     # синоним history_materialized
                    "ticks_in_window": int,        # число тиков в окне
                    "error": str | None,           # текст ошибки или None
                }

        Raises:
            ServiceError: при ошибке регистрации или невалидном окне
                (date_from > date_to и т.п.).

        Per v6 W0: НЕ поглощать ошибки best-effort — структурный result +
        exception raise на критичных failure modes (registration, validation).
        Catchup-fail допустим best-effort, но ВОЗВРАЩАЕТСЯ в result.error.
        """
        self._assert("scheduler.add_job", job_id)

        registered_job_id: str | None = None
        history_materialized = False
        catchup_scheduled = False
        ticks_in_window = 0
        error: str | None = None

        # 1. Регистрация в APScheduler через ``SchedulerManager.schedule_cron``.
        #    ``schedule_cron`` — sync, offload в thread чтобы не блокировать loop.
        try:
            from src.backend.core.scheduler import get_scheduler_manager

            manager = get_scheduler_manager()
            registered_job_id = await asyncio.to_thread(
                manager.schedule_cron,
                name=job_id,
                cron_expr=cron_expr,
                callable_ref=func,
                timezone=timezone,
                replace_existing=True,
            )
        except Exception as exc:
            _logger.warning("Failed to register job %s: %s", job_id, exc)
            error = f"registration failed: {exc}"
            return {
                "job_id": job_id,
                "registered": False,
                "history_materialized": False,
                "catchup_scheduled": False,
                "ticks_in_window": 0,
                "error": error,
            }

        # 2. Catchup-materialization (только при catchup=True).
        #    Per v6: await + structured status, НЕ fire-and-forget.
        if catchup:
            try:
                from apscheduler.triggers.cron import CronTrigger

                from src.backend.services.scheduler.backfill import BackfillService

                window_days = max(1, int(catchup_window_days))
                trigger = CronTrigger.from_crontab(cron_expr, timezone=timezone)
                now = datetime.now(tz=_tz.utc)
                service = BackfillService(
                    self.get_run_history_store(), max_window_days=window_days
                )
                report = await service.materialize_window(
                    job_id=job_id,
                    trigger=trigger,
                    date_from=now - timedelta(days=window_days),
                    date_to=now,
                    catchup=True,
                )
                history_materialized = True
                catchup_scheduled = True
                ticks_in_window = report.ticks_in_window
                _logger.info(
                    "catchup materialized job_id=%s ticks=%d pending=%d",
                    job_id,
                    report.ticks_in_window,
                    report.materialized,
                )
            except Exception as exc:
                # Per v6: НЕ поглощать без structured result — записать в
                # result.error, но НЕ raise (registration уже прошла).
                _logger.warning("catchup failed job_id=%s: %s", job_id, exc)
                error = f"catchup failed: {exc}"

        return {
            "job_id": registered_job_id or job_id,
            "registered": registered_job_id is not None,
            "history_materialized": history_materialized,
            "catchup_scheduled": catchup_scheduled,
            "ticks_in_window": ticks_in_window,
            "error": error,
        }

    def remove_job(self, job_id: str) -> None:
        """Удалить задачу из планировщика.

        Args:
            job_id: ID задачи для удаления.

        """
        self._assert("scheduler.remove_job", job_id)
        try:
            from src.backend.core.scheduler import get_scheduler_manager

            manager = get_scheduler_manager()
            manager.remove_job(job_id)
        except Exception as exc:
            _logger.warning("Failed to remove job %s: %s", job_id, exc)
            raise ServiceError(f"Failed to remove job: {exc}") from exc

    def get_run_history_store(self) -> Any:
        """RunHistoryStore для backfill/catchup (ADR-0346, P3-13 wiring).

        Ленивая инициализация: session_factory из app-конфигурации при
        первом вызове. Capability-check: ``scheduler.run_history``.
        """
        self._assert("run_history", "scheduler")

        if self._session_factory is None:
            raise ServiceError(
                "session_factory not configured — передайте async_sessionmaker "
                "в SchedulerFacade(session_factory=...) при создании"
            )
        if self._run_history_store is None:
            from src.backend.services.scheduler.run_history import RunHistoryStore

            self._run_history_store = RunHistoryStore(self._session_factory)
        return self._run_history_store
