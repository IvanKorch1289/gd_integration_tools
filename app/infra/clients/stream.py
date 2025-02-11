from faststream import FastStream
from faststream.redis import RedisBroker, RedisRouter

from app.config.settings import settings
from app.utils.logging_service import stream_logger


# Инициализация FastStream и Redis брокера
redis_broker = RedisBroker(
    url=f"{settings.redis.redis_url}/{settings.redis.db_queue}",
    max_connections=settings.redis.max_connections,
    socket_timeout=settings.redis.socket_timeout,
    socket_connect_timeout=settings.redis.socket_connect_timeout,
    retry_on_timeout=settings.redis.retry_on_timeout,
    logger=stream_logger,
)

stream_client = FastStream(broker=redis_broker, logger=stream_logger)

redis_router = RedisRouter()
redis_broker.include_router(redis_router)
