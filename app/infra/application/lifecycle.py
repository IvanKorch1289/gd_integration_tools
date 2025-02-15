from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.infra.setup_infra import ending, starting
from app.tasks import broker
from app.utils.logging_service import app_logger


__all__ = ("lifespan",)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Контекстный менеджер для управления жизненным циклом приложения.

    Запускает планировщик задач и устанавливает лимиты запросов.
    Останавливает планировщик при завершении работы приложения.
    """

    app_logger.info("Start...")

    try:
        await starting()
        if not broker.is_worker_process:
            app_logger.info("TaskiQ broker started successfully")
            await broker.startup()
        app_logger.info("Application started successfully")
        yield
    except Exception:
        app_logger.critical("Error by starting", exc_info=True)
    finally:
        app_logger.info("Shutdown...")
        if not broker.is_worker_process:
            app_logger.info("TaskiQ broker stopped successfully")
            await broker.shutdown()
        await ending()
        app_logger.info("Application shutdown complete")
