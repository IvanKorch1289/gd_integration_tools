from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config.settings import settings
from app.infra.db.database import db_initializer
from app.utils.logging_service import scheduler_logger


__all__ = (
    "scheduler_manager",
    "SchedulerManager",
)


class SchedulerManager:
    def __init__(self):
        self.logger = scheduler_logger
        self.scheduler = AsyncIOScheduler(
            timezone="Europe/Moscow",
            coalesce=True,
            max_instances=1,
            misfire_grace_time=60,
            logger=scheduler_logger,
            jobstores={
                "default": SQLAlchemyJobStore(
                    url=settings.database.sync_connection_url,
                    engine=db_initializer.sync_engine,
                    engine_options={"pool_pre_ping": True, "pool_size": 10},
                ),
                "backup": MemoryJobStore(),  # Дополнительное хранилище
            },
            executors={
                "async": {"type": "asyncio"},
                "default": {"type": "threadpool", "max_workers": 20},
            },
        )

    async def start(self):
        """Запустить планировщик при старте приложения."""
        self.scheduler.start()

    async def stop(self):
        """Остановить планировщик при завершении."""
        self.scheduler.shutdown()


scheduler_manager = SchedulerManager()
