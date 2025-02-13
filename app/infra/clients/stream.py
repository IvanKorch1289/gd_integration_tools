import uuid
from datetime import datetime, timedelta
from functools import wraps
from logging import Logger
from typing import Any, Callable, Coroutine, Dict, Optional, TypeVar

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from faststream import Context, FastStream
from faststream.kafka import KafkaBroker, KafkaRouter
from faststream.redis import RedisBroker, RedisMessage, RedisRouter

from app.config.settings import settings
from app.utils.logging_service import stream_logger


__all__ = (
    "stream_client",
    "StreamClient",
)


T = TypeVar("T")


class StreamClient:
    def __init__(self):
        self.stream_client = FastStream(logger=stream_logger)
        self.settings = settings.redis
        self.redis_broker = None
        self.kafka_broker = None
        self.redis_router = None
        self.kafka_router = None
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()

    def add_redis_broker(self):
        self.redis_broker = RedisBroker(
            url=f"{self.settings.redis_url}/{self.settings.db_queue}",
            max_connections=self.settings.max_connections,
            socket_timeout=self.settings.socket_timeout,
            socket_connect_timeout=self.settings.socket_connect_timeout,
            retry_on_timeout=self.settings.retry_on_timeout,
            logger=stream_logger,
            db=self.settings.db_queue,
        )

    def add_kafka_broker(self):
        self.kafka_broker = KafkaBroker(
            bootstrap_servers=settings.queue.bootstrap_servers
        )

    def add_redis_router(self):
        if self.redis_broker is None:
            raise ValueError("Redis broker is not initialized")
        self.redis_router = RedisRouter()
        self.redis_broker.include_router(self.redis_router)

    def add_kafka_router(self):
        if self.kafka_broker is None:
            raise ValueError("Kafka broker is not initialized")
        self.kafka_router = KafkaRouter()
        self.kafka_broker.include_router(self.kafka_router)

    async def publish_to_kafka(
        self,
        topic: str,
        message: Dict[str, Any],
        key: Optional[str] = None,
        partition: Optional[int] = None,
    ):
        if self.kafka_broker is None:
            raise ValueError("Kafka broker is not initialized")

        await self.kafka_broker.publish(
            message,
            topic=topic,
            key=key,
            partition=partition,
        )

    async def publish_to_redis(
        self,
        stream: str,
        message: Dict[str, Any],
        headers: Dict[str, Any] = None,
        delay: Optional[timedelta] = None,
        scheduler: Optional[str] = None,
    ):
        """
        Публикует сообщение в Redis сразу, с задержкой или по расписанию.
        """
        if self.redis_broker is None:
            raise ValueError("Redis broker is not initialized")

        if delay and scheduler:
            raise ValueError("Cannot use both delay and scheduler")

        # Если нет расписания - публикуем сразу
        if not delay and not scheduler:
            return await self.redis_broker.publish(
                message=message, headers=headers, stream=stream
            )

        # Создаем уникальный ID задачи
        job_id = f"redis_job_{uuid.uuid4()}"

        # Определяем триггер
        if delay:
            trigger = DateTrigger(run_date=datetime.now() + delay)
        else:
            trigger = CronTrigger.from_crontab(scheduler)

        # Добавляем задачу в планировщик
        self.scheduler.add_job(
            self.redis_broker.publish,
            trigger=trigger,
            args=(stream, message),
            id=job_id,
            replace_existing=True,
        )

    def retry_with_backoff(
        self,
        max_attempts: int,
        delay: timedelta,
        stream: str,
    ) -> Callable[
        [Callable[..., Coroutine[Any, Any, T]]],
        Callable[..., Coroutine[Any, Any, T]],
    ]:
        """
        Декоратор для повторного выполнения функции с экспоненциальной задержкой.

        Args:
            max_attempts: Максимальное количество попыток.
            delay: Задержка между попытками.
            stream: Имя потока Redis для повторной публикации.

        Returns:
            Декоратор для асинхронных функций.
        """

        def decorator(
            func: Callable[..., Coroutine[Any, Any, T]]
        ) -> Callable[..., Coroutine[Any, Any, T]]:
            @wraps(func)
            async def wrapper(
                *args: Any,
                message: Context = Context(),
                logger: Logger = stream_logger,
                **kwargs: Any,
            ) -> Optional[T]:
                headers = message.raw_message.get("headers", None)
                attempt = 1
                if headers is not None:
                    attempt = headers.get("attempt", 1)

                try:
                    return await func(*args, **kwargs)
                except Exception:
                    logger.error(f"Error in {func.__name__}", exc_info=True)
                    if attempt >= max_attempts - 1:
                        logger.error("Max retries reached")
                        return None
                    logger.error(attempt)
                    return await stream_client.publish_to_redis(
                        stream=stream,
                        message=message.body,
                        delay=delay,
                        headers={**message.headers, "attempt": attempt + 1},
                    )

            return wrapper

        return decorator

    async def publish_with_delay(
        self, stream: str, message: Any, delay: timedelta
    ) -> None:
        """
        Публикует сообщение в указанный поток с задержкой.
        """
        await self.publish_to_redis(
            stream=stream,
            message=message,
            delay=delay,
        )

    async def start_brokers(self):
        await self.redis_broker.start()
        # await self.kafka_broker.start()

    async def stop_brokers(self):
        await self.redis_broker.start()
        # await self.kafka_broker.start()


stream_client = StreamClient()
stream_client.add_redis_broker()
stream_client.add_kafka_broker()
stream_client.add_redis_router()
stream_client.add_kafka_router()
