from taskiq_pipelines import PipelineMiddleware
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from app.config.settings import settings
from app.utils.middlewares.tasks_log import LoggingMiddleware


__all__ = ("get_broker",)


def get_broker() -> ListQueueBroker:
    result_backend = RedisAsyncResultBackend(
        redis_url=f"{settings.redis.redis_url}/{settings.redis.db_tasks}",
    )

    broker = ListQueueBroker(
        url=f"{settings.redis.redis_url}/{settings.redis.db_tasks}",
        queue_name=settings.redis.name_tasks_queue,
    ).with_result_backend(result_backend)
    broker.add_middlewares(LoggingMiddleware(), PipelineMiddleware())

    return broker
