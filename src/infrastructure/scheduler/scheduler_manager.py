from functools import lru_cache
from typing import Any

from src.core.config.constants import consts
from src.core.config.settings import settings
from src.infrastructure.external_apis.logging_service import scheduler_logger
from src.infrastructure.scheduler.scheduled_tasks import check_all_services

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
        Использует SQLAlchemyJobStore в качестве основного хранилища задач
        и MemoryJobStore в качестве резервного.
        Настраивает как асинхронные, так и пул-потоковые исполнители.
        """
        from apscheduler.jobstores.memory import MemoryJobStore
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        from src.infrastructure.database.database import db_initializer

        self.logger = scheduler_logger
        self.scheduler = AsyncIOScheduler(
            timezone=settings.scheduler.timezone,
            coalesce=settings.scheduler.coalesce,
            max_instances=settings.scheduler.max_instances,
            misfire_grace_time=settings.scheduler.misfire_grace_time,
            logger=scheduler_logger,
            jobstores={
                settings.scheduler.default_jobstore_name: SQLAlchemyJobStore(
                    url=settings.database.sync_connection_url,
                    engine=db_initializer.sync_engine,
                    engine_options={"pool_pre_ping": True, "pool_size": 10},
                ),
                settings.scheduler.backup_jobstore_name: MemoryJobStore(),  # Резервное хранилище
            },
            executors=settings.scheduler.executors,
        )
        self._event_handlers = {}  # Словарь для хранения обработчиков событий

    async def start(self):
        """
        Запускает планировщик при старте приложения.
        """
        self.scheduler.start()

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
    return manager


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat ``scheduler_manager``."""
    if name == "scheduler_manager":
        return get_scheduler_manager()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
