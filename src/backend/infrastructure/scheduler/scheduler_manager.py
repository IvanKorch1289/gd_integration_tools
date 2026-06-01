from functools import lru_cache
from typing import Any

from src.backend.core.config.constants import consts
from src.backend.core.config.settings import settings
from src.backend.infrastructure.logging import get_logger
from src.backend.infrastructure.scheduler.scheduled_tasks import (
    check_all_services,
    consolidate_idle_sessions,
)

scheduler_logger = get_logger("scheduler")

__all__ = ("scheduler_manager", "SchedulerManager", "get_scheduler_manager")


class SchedulerManager:
    """
    Менеджер для управления экземпляром APScheduler.
    Класс инициализирует и управляет жизненным циклом планировщика,
    включая его запуск и остановку.
    """

    def __init__(self):
        """
        Инициализирует планировщик с указанной конфигурацией.

        Default jobstore — SQLAlchemyJobStore поверх sync_engine (durable).
        Если sync_engine отсутствует (Wave F.3: sync-драйвер не установлен),
        default-jobstore тоже становится MemoryJobStore — durable отсутствует,
        warning в лог.

        Настраивает как асинхронные, так и пул-потоковые исполнители.
        """
        from apscheduler.jobstores.memory import MemoryJobStore
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        from src.backend.infrastructure.database.database import db_initializer

        self.logger = scheduler_logger

        if db_initializer.sync_engine is None:
            self.logger.warning(
                "APScheduler: sync_engine отсутствует — default-jobstore "
                "становится MemoryJobStore (durable отключен). "
                "Установите sync-драйвер БД для durable-режима."
            )
            default_jobstore = MemoryJobStore()
        else:
            default_jobstore = SQLAlchemyJobStore(
                url=settings.database.sync_connection_url,
                engine=db_initializer.sync_engine,
                engine_options={"pool_pre_ping": True, "pool_size": 10},
            )

        self.scheduler = AsyncIOScheduler(
            timezone=settings.scheduler.timezone,
            coalesce=settings.scheduler.coalesce,
            max_instances=settings.scheduler.max_instances,
            misfire_grace_time=settings.scheduler.misfire_grace_time,
            logger=scheduler_logger,
            jobstores={
                settings.scheduler.default_jobstore_name: default_jobstore,
                settings.scheduler.backup_jobstore_name: MemoryJobStore(),
            },
            executors=settings.scheduler.executors,
        )
        self._event_handlers = {}  # Словарь для хранения обработчиков событий
        self._default_jobstore_is_memory: bool = isinstance(
            default_jobstore, MemoryJobStore
        )

    async def start(self):
        """
        Запускает планировщик при старте приложения.

        Sprint 16 Wave 5 (M-9/CP-22): подключает Prometheus-listeners для
        ``scheduler_job_executions_total`` + регистрирует тип jobstore
        (CRITICAL alert при ``MemoryJobStore`` в production).
        """
        self.scheduler.start()

        try:
            from src.backend.infrastructure.scheduler.observability import (
                attach_scheduler_metrics,
                report_jobstore_type,
            )

            attach_scheduler_metrics(self.scheduler)
            report_jobstore_type(
                is_memory=self._default_jobstore_is_memory,
                is_production=settings.app.environment == "production",
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Scheduler observability bootstrap skipped: %s", exc)

    async def stop(self):
        """
        Останавливает планировщик при завершении работы приложения.
        """
        self.scheduler.shutdown()

    def register_job_cleanup(self, job_name: str):
        """
        Регистрирует обработчик для автоматической очистки задач с указанным именем.

        Args:
            job_name (str): Имя задачи, для которой регистрируется обработчик.
        """
        from apscheduler.events import EVENT_JOB_EXECUTED

        if job_name in self._event_handlers:
            self.logger.warning(
                f"Обработчик для задачи '{job_name}' уже зарегистрирован."
            )
            return

        def cleanup_job(event):
            """Обработчик для удаления задачи после её выполнения."""
            if event.job_id.startswith(job_name):
                try:
                    self.scheduler.remove_job(event.job_id)
                    self.logger.info(f"Задача '{event.job_id}' успешно удалена.")
                except Exception as exc:
                    self.logger.error(
                        f"Ошибка при удалении задачи '{event.job_id}': {str(exc)}"
                    )

        # Регистрируем обработчик
        self.scheduler.add_listener(cleanup_job, EVENT_JOB_EXECUTED)
        self._event_handlers[job_name] = cleanup_job
        self.logger.info(f"Зарегистрирован обработчик для задачи '{job_name}'.")

    def unregister_job_cleanup(self, job_name: str):
        """
        Удаляет обработчик для задач с указанным именем.

        Args:
            job_name (str): Имя задачи, для которой удаляется обработчик.
        """
        if job_name not in self._event_handlers:
            self.logger.warning(f"Обработчик для задачи '{job_name}' не найден.")
            return

        # Удаляем обработчик
        self.scheduler.remove_listener(self._event_handlers[job_name])
        del self._event_handlers[job_name]
        self.logger.info(f"Обработчик для задачи '{job_name}' удалён.")

    def cleanup_all_jobs_by_name(self, job_name: str):
        """
        Очищает все задачи с указанным именем.

        Args:
            job_name (str): Имя задачи, которую необходимо очистить.
        """
        jobs = self.scheduler.get_jobs()
        for job in jobs:
            if job.id.startswith(job_name):
                try:
                    self.scheduler.remove_job(job.id)
                    self.logger.info(f"Задача '{job.id}' успешно удалена.")
                except Exception as exc:
                    self.logger.error(
                        f"Ошибка при удалении задачи '{job.id}': {str(exc)}"
                    )

    # ── Sprint 12 K3 W2: cron API для UI / admin REST ──

    def schedule_cron(
        self,
        name: str,
        cron_expr: str,
        callable_ref: Any,
        *,
        timezone: str = "Europe/Moscow",
        replace_existing: bool = True,
    ) -> str:
        """Регистрирует cron-job через APScheduler и возвращает ``job_id``.

        Args:
            name: Человекочитаемое имя задачи (используется как ``id``).
            cron_expr: cron-строка (croniter format) — будет распарсена
                CronTrigger через ``CronTrigger.from_crontab(cron_expr,
                timezone=tz)``.
            callable_ref: Функция (sync/async), которая будет вызвана.
            timezone: IANA timezone name.
            replace_existing: При ``True`` перезаписывает существующую
                job с тем же ``id``.

        Returns:
            ``job_id`` зарегистрированной задачи (равно ``name``).
        """
        from apscheduler.triggers.cron import CronTrigger

        trigger = CronTrigger.from_crontab(cron_expr, timezone=timezone)
        job = self.scheduler.add_job(
            func=callable_ref,
            trigger=trigger,
            id=name,
            name=name,
            replace_existing=replace_existing,
            jobstore=settings.scheduler.default_jobstore_name,
            executor="async",
        )
        self.logger.info(
            f"Cron job {name!r} зарегистрирован (cron={cron_expr!r}, tz={timezone})."
        )
        return str(job.id)

    def list_jobs(self) -> list[dict[str, Any]]:
        """Список всех scheduled jobs (для admin/cron/dashboard)."""
        result: list[dict[str, Any]] = []
        for job in self.scheduler.get_jobs():
            next_run = getattr(job, "next_run_time", None)
            trigger_str = str(getattr(job, "trigger", ""))
            result.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": next_run.isoformat() if next_run else None,
                    "trigger": trigger_str,
                    "paused": next_run is None,
                }
            )
        return result

    def pause_job(self, job_id: str) -> bool:
        """Приостанавливает scheduled job. Возвращает ``True`` если найден."""
        try:
            self.scheduler.pause_job(job_id)
            self.logger.info(f"Job {job_id!r} приостановлен.")
            return True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"pause_job({job_id!r}) failed: {exc}")
            return False

    def resume_job(self, job_id: str) -> bool:
        """Возобновляет scheduled job. Возвращает ``True`` если найден."""
        try:
            self.scheduler.resume_job(job_id)
            self.logger.info(f"Job {job_id!r} возобновлён.")
            return True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"resume_job({job_id!r}) failed: {exc}")
            return False

    def run_job_now(self, job_id: str) -> bool:
        """Триггерит немедленное выполнение job (для page 14 ``Run now`` button).

        APScheduler не имеет explicit ``run_now``; используется
        ``modify_job(next_run_time=datetime.now())``.
        """
        from datetime import datetime
        from datetime import timezone as _tz

        try:
            self.scheduler.modify_job(job_id, next_run_time=datetime.now(_tz.utc))
            return True
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"run_job_now({job_id!r}) failed: {exc}")
            return False


@lru_cache(maxsize=1)
def get_scheduler_manager() -> SchedulerManager:
    """Lazy singleton ``SchedulerManager`` (Wave 6.1).

    На первое обращение:
    - регистрирует job-cleanup ``resume_*`` (см. ``register_job_cleanup``);
    - добавляет canonical job ``check_all_services``.

    Это переносит side-effects из module-level в первое обращение —
    все DB/scheduler-инициализации делаются лениво.
    """
    manager = SchedulerManager()
    manager.register_job_cleanup("resume_")
    manager.scheduler.add_job(
        func=check_all_services,
        trigger="interval",
        minutes=consts.CHECK_SERVICES_JOB["minutes"],
        replace_existing=True,
        id=consts.CHECK_SERVICES_JOB["name"],
        name="Проверка состояния всех сервисов",
        jobstore=settings.scheduler.default_jobstore_name,
        executor="async",
    )

    # S19 K4 W4b: LangMem consolidation — register only when cron expr is set
    try:
        from src.backend.core.config.ai_2026 import langmem_settings

        if langmem_settings.consolidation_schedule_cron:
            manager.schedule_cron(
                name="langmem_consolidation",
                cron_expr=langmem_settings.consolidation_schedule_cron,
                callable_ref=consolidate_idle_sessions,
                timezone=settings.scheduler.timezone,
            )
    except Exception as exc:  # noqa: BLE001
        manager.logger.warning(
            "LangMem consolidation job registration skipped: %s", exc
        )

    return manager


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat ``scheduler_manager``."""
    if name == "scheduler_manager":
        return get_scheduler_manager()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
