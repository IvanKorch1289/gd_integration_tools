"""SchedulerFacade — capability-checked фасад для scheduler.

Provides capability-checked access to APScheduler for extensions.
"""

from __future__ import annotations

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

    def add_job(
        self, job_id: str, func: Any, trigger: str = "cron", **trigger_kwargs: Any
    ) -> None:
        """Добавить задачу в планировщик.

        Args:
            job_id: Уникальный ID задачи.
            func: Callable для выполнения.
            trigger: Тип триггера (cron/interval/date).
            **trigger_kwargs: Аргументы триггера (e.g., hour=9, minute=0).

        """
        self._assert("scheduler.add_job", job_id)
        try:
            from src.backend.core.scheduler import get_scheduler_manager

            manager = get_scheduler_manager()
            manager.add_job(job_id=job_id, func=func, trigger=trigger, **trigger_kwargs)

            # ADR-0346 P3-13: catchup — materialize run-history для cron-job'а
            # (opt-in: catchup=True в trigger_kwargs; окно ограничено конфигом).
            if trigger == "cron" and trigger_kwargs.get("catchup"):
                self._materialize_catchup(job_id, trigger_kwargs)
        except Exception as exc:
            _logger.warning("Failed to add job %s: %s", job_id, exc)
            raise ServiceError(f"Failed to add job: {exc}") from exc

    def _materialize_catchup(self, job_id: str, trigger_kwargs: dict[str, Any]) -> None:
        """Материализовать run-history за catchup-окно (best-effort).

        ADR-0346: ошибка materialize НЕ срывает регистрацию job'а
        (история — вспомогательный контур), но логируется.
        """
        try:
            from datetime import datetime, timedelta, timezone

            from apscheduler.triggers.cron import CronTrigger

            from src.backend.services.scheduler.backfill import BackfillService

            trigger = CronTrigger(
                **{k: v for k, v in trigger_kwargs.items() if k != "catchup"}
            )
            window_days = int(trigger_kwargs.get("catchup_window_days", 1))
            now = datetime.now(tz=timezone.utc)
            service = BackfillService(
                self.get_run_history_store(), max_window_days=max(window_days, 1)
            )
            report = service.materialize_window(
                job_id=job_id,
                trigger=trigger,
                date_from=now - timedelta(days=window_days),
                date_to=now,
                catchup=True,
            )
            _logger.info(
                "catchup materialized job_id=%s ticks=%d pending=%d",
                job_id,
                report.ticks_in_window,
                report.materialized,
            )
        except Exception as exc:  # ADR-0346: best-effort, не срывает add_job
            _logger.warning("catchup materialize failed job_id=%s: %s", job_id, exc)

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
