import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from faststream import BaseMiddleware, ExceptionMiddleware, FastStream
from faststream.broker.message import StreamMessage
from faststream.kafka.fastapi import KafkaRouter
from faststream.redis.fastapi import RedisRouter

from app.config.settings import settings
from app.infra.application.scheduler import scheduler_manager
from app.utils.logging_service import stream_logger


__all__ = (
    "stream_client",
    "StreamClient",
)


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


class StreamClient:
    def __init__(self):
        self.stream_client = FastStream(logger=stream_logger)
        self.settings = settings.redis
        self.kafka_broker = None
        self.redis_router = None
        self.kafka_router = None
        self.scheduler = scheduler_manager.scheduler
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
                ExceptionMiddleware(
                    handlers={
                        Exception: lambda exc: stream_logger.info(
                            "Exception", exc_info=True
                        )
                    }
                ),
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
        tz = timezone(timedelta(hours=3))
        if delay:
            trigger = DateTrigger(run_date=datetime.now(tz) + delay)
        else:
            trigger = CronTrigger.from_crontab(scheduler)

        # Добавляем задачу в планировщик
        self.scheduler.add_job(
            self.redis_router.publish,
            trigger=trigger,
            args=(stream, message),
            kwargs={"headers": headers},
            id=job_id,
            replace_existing=True,
            remove_after_completion=True,
        )


stream_client = StreamClient()
