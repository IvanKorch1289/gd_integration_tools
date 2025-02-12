from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config.settings import settings
from app.infra.clients.stream import stream_client
from app.infra.db.database import db_initializer
from app.utils.health_check import health_check
from app.utils.logging_service import scheduler_logger


__all__ = (
    "SchedulerManager",
    "health_check",
)

JOBSTORES = {
    "default": SQLAlchemyJobStore(
        url=settings.database.sync_connection_url,
        engine=db_initializer.sync_engine,
        engine_options={"pool_pre_ping": True, "pool_size": 10},
    ),
    "backup": MemoryJobStore(),  # Дополнительное хранилище
}


async def check_all_services():
    """
    Проверяет состояние всех сервисов.
    """
    result = await health_check.check_all_services()

    if not result.get("is_all_services_active"):
        data = {
            "to_emails": ["cards25@rt.bak"],
            "subject": "Обнаружено неактивное состояние сервисов",
            "message": "Обнаружено неактивное состояние сервисов. Проверьте работу сервисов и попробуйте позже.",
        }
        await stream_client.publish_to_redis(
            message=data, stream="email_send_stream"
        )


class SchedulerManager:
    def __init__(self):
        self.logger = scheduler_logger
        self.scheduler = AsyncIOScheduler(
            timezone="Europe/Moscow",
            coalesce=True,
            max_instances=1,
            misfire_grace_time=60,
            logger=self.logger,
            jobstores=JOBSTORES,
        )
        self.setup_scheduler()

    def setup_scheduler(self):
        # Добавляем задачу в планировщик
        self.scheduler.add_job(
            func=check_all_services,
            trigger=CronTrigger(
                hour="6-22", minute="0,30", day_of_week="mon-fri"
            ),
        )

    async def start_scheduler(self):
        try:
            self.scheduler.start()
            self.logger.info("Scheduler started successfully")
        except Exception:
            self.logger.error("Error initializing scheduler", exc_info=True)
            raise

    async def stop_scheduler(self):
        try:
            self.scheduler.shutdown()
            self.logger.info("Scheduler stopped successfully")
        except Exception:
            self.logger.error("Error stopped scheduler", exc_info=True)


scheduler_manager = SchedulerManager()
