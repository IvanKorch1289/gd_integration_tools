from asyncio import to_thread

from types import CoroutineType

from app.infra.application.scheduler import scheduler_manager
from app.infra.clients.logger import graylog_handler
from app.infra.clients.redis import redis_client
from app.infra.clients.smtp import smtp_client
from app.infra.clients.storage import s3_client
from app.infra.db.database import db_initializer
from app.utils.decorators.limiting import init_limiter
from app.utils.logging_service import app_logger


__all__ = (
    "starting",
    "ending",
)


starting_operations = [
    redis_client.ensure_connected,
    ("graylog_client", lambda: to_thread(graylog_handler.connect)),
    db_initializer.initialize_async_pool,
    s3_client.connect,
    smtp_client.initialize_pool,
    init_limiter,
    redis_client.create_initial_streams,
    scheduler_manager.start,
]

ending_operations = [
    scheduler_manager.stop,
    smtp_client.close_pool,
    s3_client.close,
    db_initializer.close,
    ("graylog_client", lambda: to_thread(graylog_handler.close)),
    redis_client.close,
]


async def perform_infrastructure_operation(components: list) -> None:
    for component in components:
        try:
            coro = None

            if isinstance(component, tuple):
                _, func = component
                coro = func()
            else:
                coro = component()

            if isinstance(coro, CoroutineType):
                await coro

            app_logger.info(f"Operation {coro.__name__} succeeded")
        except Exception as exc:
            app_logger.critical(
                f"Operation {coro.__name__} failed: {str(exc)}", exc_info=True
            )
            raise


async def starting() -> None:
    await perform_infrastructure_operation(components=starting_operations)


async def ending() -> None:
    await perform_infrastructure_operation(components=ending_operations)
