from taskiq_pipelines import PipelineMiddleware
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend

from app.config.settings import settings
from app.utils.middlewares.tasks_log import LoggingMiddleware


__all__ = ("broker",)


redis_url = f"{settings.redis.redis_url}/{settings.redis.db_tasks}"

result_backend = RedisAsyncResultBackend(redis_url=redis_url)

broker = ListQueueBroker(
    url=redis_url,
    queue_name=settings.redis.name_tasks_queue,
).with_result_backend(result_backend)

broker.add_middlewares(LoggingMiddleware(), PipelineMiddleware())
