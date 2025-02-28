from app.config.constants import CHECK_SERVICES_JOB
from app.config.settings import settings
from app.schemas.base import EmailSchema
from app.utils.logging_service import scheduler_logger


__all__ = (
    "scheduler_manager",
    "SchedulerManager",
)


class SchedulerManager:
    """
    A manager class for handling the APScheduler instance.
    This class initializes and manages the lifecycle of the scheduler,
    including starting and stopping it.
    """

    def __init__(self):
        """
        Initializes the scheduler with the specified configuration.
        Uses SQLAlchemyJobStore as the primary job store and MemoryJobStore as a backup.
        Configures both async and threadpool executors.
        """
        from apscheduler.jobstores.memory import MemoryJobStore
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        from app.infra.db.database import db_initializer

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
                settings.scheduler.backup_jobstore_name: MemoryJobStore(),  # Backup job store
            },
            executors=settings.scheduler.executors,
        )

    async def start(self):
        """
        Starts the scheduler when the application starts.
        """
        self.scheduler.start()

    async def stop(self):
        """
        Stops the scheduler when the application shuts down.
        """
        self.scheduler.shutdown()


scheduler_manager = SchedulerManager()


async def check_all_services():
    """
    Checks the health status of all services.
    If any service is inactive, sends an email notification via Redis stream.
    """
    from app.utils.health_check import get_healthcheck_service

    try:
        scheduler_logger.info("Starting health check of all services...")

        async with get_healthcheck_service() as health_check:
            result = await health_check.check_all_services()

        if not result.get("is_all_services_active"):
            from app.infra.clients.stream import stream_client

            data = {
                "to_emails": ["cards25@rt.bak"],
                "subject": "Inactive Services Detected",
                "message": "Inactive services detected. Please check the services and try again later.",
            }

            await stream_client.publish_to_redis(
                message=EmailSchema.model_validate(data),
                stream=settings.redis.get_stream_name("email"),
            )
        scheduler_logger.info(f"Health check completed. Result: {result}")
    except Exception as exc:
        scheduler_logger.error(
            f"Error during health check: {str(exc)}", exc_info=True
        )
        raise  # Exception will be handled by global exception handler


scheduler_manager.scheduler.add_job(
    func=check_all_services,
    trigger="interval",
    minutes=CHECK_SERVICES_JOB["minutes"],  # Check every minute
    replace_existing=True,
    id=CHECK_SERVICES_JOB["name"],
    name="Check health status of all services",
    jobstore=settings.scheduler.default_jobstore_name,
    executor="async",
)
