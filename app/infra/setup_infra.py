from app.infra.db.database import db_initializer
from app.infra.db.mongo import mongo_client
from app.infra.logger import graylog_handler
from app.infra.queue import queue_client
from app.infra.redis import redis_client
from app.infra.smtp import smtp_client
from app.infra.storage import s3_client
from app.infra.stream_manager import stream_client
from app.services.infra_services.events import event_service
from app.services.infra_services.kafka import queue_service
from app.services.infra_services.queue_handlers import process_order
from app.utils.decorators.limiting import init_limiter
from app.utils.logging_service import app_logger


__all__ = (
    "starting",
    "ending",
)


starting_operations = [
    graylog_handler.connect(),
    redis_client.ensure_connected(),
    db_initializer.initialize_async_pool(),
    s3_client.connect(),
    smtp_client.initialize_pool(),
    event_service.register_handlers(),
    stream_client.start_consumer(),
    init_limiter(),
    queue_client.initialize(),
    queue_client.create_topics(["required_topics"]),
    queue_service.start_message_consumption(),
    queue_service.register_handler("orders", process_order),
    mongo_client.connect(),
]

ending_operations = [
    stream_client.stop_consumer(),
    db_initializer.close(),
    s3_client.close(),
    smtp_client.close_pool(),
    queue_service.stop_message_consumption(),
    queue_client.close(),
    redis_client.close(),
    graylog_handler.close(),
    mongo_client.close(),
]


async def perform_infrastructure_operation(components: list) -> None:
    for component in components:
        try:
            await component
        except Exception as exc:
            app_logger.critical(
                f"Operation {component.__name__} failed: {str(exc)}"
            )
            raise


async def starting() -> None:
    await perform_infrastructure_operation(components=starting_operations)


async def ending() -> None:
    await perform_infrastructure_operation(components=ending_operations)
