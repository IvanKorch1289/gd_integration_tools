import uuid
from datetime import datetime, timedelta
from functools import wraps
from logging import Logger
from typing import Any, Awaitable, Callable, Coroutine, Dict, Optional, TypeVar

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from faststream import BaseMiddleware, Context, ExceptionMiddleware, FastStream
from faststream.broker.message import StreamMessage
from faststream.kafka.fastapi import KafkaRouter
from faststream.redis.fastapi import RedisRouter

from app.config.settings import settings
from app.utils.logging_service import stream_logger


__all__ = (
    "stream_client",
    "StreamClient",
)


T = TypeVar("T")


class MessageLoggingMiddleware(BaseMiddleware):
    async def consume_scope(
        self,
        call_next: Callable[[Any], Awaitable[Any]],
        msg: StreamMessage[Any],
    ) -> Any:
        stream_logger.info(f"Subscribe: {msg}")
        return await call_next(msg)

    async def publish_scope(
        self,
        call_next: Callable[..., Awaitable[Any]],
        msg: Any,
        **options: Any,
    ) -> Any:
        stream_logger.info(f"Publish: {msg}")
        return await call_next(msg, **options)


exc_middleware = ExceptionMiddleware(
    handlers={
        Exception: lambda exc: stream_logger.info(f"Exception: {repr(exc)}")
    }
)


class StreamClient:
    def __init__(self):
        self.stream_client = FastStream(logger=stream_logger)
        self.settings = settings.redis
        self.kafka_broker = None
        self.redis_router = None
        self.kafka_router = None
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()
        self.add_redis_router()
        self.add_kafka_router()

    def add_redis_router(self):
        self.redis_router = RedisRouter(
            url=f"{self.settings.redis_url}/{self.settings.db_queue}",
            max_connections=self.settings.max_connections,
            socket_timeout=self.settings.socket_timeout,
            socket_connect_timeout=self.settings.socket_connect_timeout,
            retry_on_timeout=self.settings.retry_on_timeout,
            logger=stream_logger,
            db=self.settings.db_queue,
            schema_url="/asyncapi",
            include_in_schema=True,
            middlewares=[
                exc_middleware,
                MessageLoggingMiddleware,
            ],
        )

    def add_kafka_router(self):
        self.kafka_router = KafkaRouter(
            bootstrap_servers=settings.queue.bootstrap_servers
        )

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
        if self.redis_router is None:
            raise ValueError("Redis router is not initialized")

        if delay and scheduler:
            raise ValueError("Cannot use both delay and scheduler")

        # Если нет расписания - публикуем сразу
        if not delay and not scheduler:
            await self.redis_router.broker.publish(
                message=message, headers=headers, stream=stream
            )
            return

        # Создаем уникальный ID задачи
        job_id = f"redis_job_{uuid.uuid4()}"

        # Определяем триггер
        if delay:
            trigger = DateTrigger(run_date=datetime.now() + delay)
        else:
            trigger = CronTrigger.from_crontab(scheduler)

        # Добавляем задачу в планировщик
        self.scheduler.add_job(
            self.redis_router.publish,
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


stream_client = StreamClient()
