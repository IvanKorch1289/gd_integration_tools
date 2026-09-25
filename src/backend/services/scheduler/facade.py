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

25.09 audit DI fix:
    ``backend`` (SchedulerBackend Protocol) и ``history_store``
    (RunHistoryStoreProtocol) — теперь injected через ``__init__``.
    Service locator внутри методов УДАЛЁН. Если deps не переданы —
    fall-back на locator для backward compat с тестами, которые
    не используют DI.

Per v6: «Заменить dict[str, Any] результата регистрации на
typed JobRegistrationResult» — теперь add_job возвращает
``JobRegistrationResult`` (dataclass). ``.to_dict()`` — для
backward compat callers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from datetime import timezone as _tz
from typing import Any

from src.backend.core.errors import ServiceError
from src.backend.core.logging import get_logger
from src.backend.services.scheduler.protocols import JobRegistrationResult

__all__ = ("SchedulerFacade", "JobRegistrationResult")

_logger = get_logger("services.scheduler.facade")


class SchedulerFacade:
    """Capability-checked фасад для scheduler.

    Args:
        capability_check: Опц. callback ``CapabilityGate.check``.
        plugin: Имя caller'а (для capability-event и audit).
        session_factory: async_sessionmaker для run-history store
            (legacy parameter — если ``history_store`` не передан,
            будет создан ``RunHistoryStore(session_factory)``).
        backend: ``SchedulerBackend`` Protocol (production: APScheduler
            wrapper). Если ``None`` → lazy resolve через
            ``get_scheduler_manager()`` (backward compat).
        history_store: ``RunHistoryStoreProtocol`` для backfill/catchup.
            Если ``None`` → constructed из ``session_factory``.

    """

    def __init__(
        self,
        *,
        capability_check: Any | None = None,
        plugin: str = "extension",
        session_factory: Any | None = None,
        backend: Any | None = None,
        history_store: Any | None = None,
    ) -> None:
        self._check = capability_check
        self._plugin = plugin
        self._session_factory = session_factory
        self._backend = backend
        self._history_store = history_store

    def _assert(self, action: str, resource: str) -> None:
        if self._check is not None:
            self._check(self._plugin, action, resource)

    def _get_backend(self) -> Any:
        """Resolve SchedulerBackend.

        25.09 audit: prefer injected ``_backend`` (DI), fall-back на
        service locator только если deps не переданы.
        """
        if self._backend is not None:
            return self._backend
        from src.backend.core.scheduler import get_scheduler_manager

        return get_scheduler_manager()

    def get_run_history_store(self) -> Any:
        """RunHistoryStore для backfill/catchup (ADR-0346, P3-13 wiring).

        25.09 audit: prefer injected ``_history_store`` (DI),
        fall-back на конструкцию из ``session_factory`` если не передан.
        """
        self._assert("run_history", "scheduler")

        if self._history_store is not None:
            return self._history_store
        if self._session_factory is None:
            raise ServiceError(
                "session_factory not configured — передайте async_sessionmaker "
                "в SchedulerFacade(session_factory=...) при создании"
            )
        from src.backend.services.scheduler.run_history import RunHistoryStore

        return RunHistoryStore(self._session_factory)

    async def add_job(
        self,
        job_id: str,
        func: Any,
        cron_expr: str,
        *,
        catchup: bool = False,
        catchup_window_days: int = 1,
        timezone: str = "Europe/Moscow",
    ) -> JobRegistrationResult:
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
            :class:`JobRegistrationResult` с статусами registered,
            history_materialized, catchup_scheduled, ticks_in_window, error.

            Используйте ``.to_dict()`` для backward compat с callers,
            которые ожидали ``dict[str, Any]``.

        Raises:
            ServiceError: при ошибке регистрации или невалидном окне
                (date_from > date_to и т.п.).

        Per v6 W0: НЕ поглощать ошибки best-effort — структурный result +
        exception raise на критичных failure modes (registration, validation).
        Catchup-fail допустим best-effort, но ВОЗВРАЩАЕТСЯ в result.error.
        """
        self._assert("scheduler.add_job", job_id)

        # 1. Регистрация через injected SchedulerBackend (25.09 audit: DI).
        #    ``schedule_cron`` — sync, offload в thread чтобы не блокировать loop.
        try:
            backend = self._get_backend()
            registered_job_id = await asyncio.to_thread(
                backend.schedule_cron,
                name=job_id,
                cron_expr=cron_expr,
                callable_ref=func,
                timezone=timezone,
                replace_existing=True,
            )
        except Exception as exc:
            _logger.warning("Failed to register job %s: %s", job_id, exc)
            return JobRegistrationResult(
                job_id=job_id,
                registered=False,
                history_materialized=False,
                catchup_scheduled=False,
                ticks_in_window=0,
                error=f"registration failed: {exc}",
            )

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
                _logger.info(
                    "catchup materialized job_id=%s ticks=%d pending=%d",
                    job_id,
                    report.ticks_in_window,
                    report.materialized,
                )
                return JobRegistrationResult(
                    job_id=registered_job_id or job_id,
                    registered=True,
                    history_materialized=True,
                    catchup_scheduled=True,
                    ticks_in_window=report.ticks_in_window,
                    error=None,
                )
            except Exception as exc:
                # Per v6: НЕ поглощать без structured result — записать в
                # result.error, но НЕ raise (registration уже прошла).
                _logger.warning("catchup failed job_id=%s: %s", job_id, exc)
                return JobRegistrationResult(
                    job_id=registered_job_id or job_id,
                    registered=True,
                    history_materialized=False,
                    catchup_scheduled=False,
                    ticks_in_window=0,
                    error=f"catchup failed: {exc}",
                )

        return JobRegistrationResult(
            job_id=registered_job_id or job_id,
            registered=True,
            history_materialized=False,
            catchup_scheduled=False,
            ticks_in_window=0,
            error=None,
        )

    def remove_job(self, job_id: str) -> None:
        """Удалить задачу из планировщика.

        Args:
            job_id: ID задачи для удаления.

        """
        self._assert("scheduler.remove_job", job_id)
        try:
            backend = self._get_backend()
            # SchedulerBackend Protocol имеет ``cancel``; SchedulerManager
            # — legacy без cancel, но ``scheduler.remove_job`` доступен
            # через ``self.scheduler`` (APScheduler). Fallback chain:
            if hasattr(backend, "cancel"):
                backend.cancel(job_id)
            elif hasattr(backend, "remove_job"):
                backend.remove_job(job_id)
            elif hasattr(backend, "scheduler"):
                backend.scheduler.remove_job(job_id)
            else:
                raise ServiceError(
                    f"Backend {type(backend).__name__} не поддерживает remove_job"
                )
        except ServiceError:
            raise
        except Exception as exc:
            _logger.warning("Failed to remove job %s: %s", job_id, exc)
            raise ServiceError(f"Failed to remove job: {exc}") from exc
