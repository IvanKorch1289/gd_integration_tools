import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from faststream import FastStream
from faststream.kafka import KafkaBroker, KafkaRouter
from faststream.redis import RedisBroker, RedisRouter

from app.config.settings import settings
from app.utils.logging_service import stream_logger


class StreamClient:
    def __init__(self):
        self.stream_client = FastStream(logger=stream_logger)
        self.redis_broker = None
        self.kafka_broker = None
        self.redis_router = None
        self.kafka_router = None
        self.scheduler = AsyncIOScheduler()
        self.scheduler.start()

    def add_redis_broker(self):
        self.redis_broker = RedisBroker(
            url=f"{settings.redis.redis_url}/{settings.redis.db_queue}",
            max_connections=settings.redis.max_connections,
            socket_timeout=settings.redis.socket_timeout,
            socket_connect_timeout=settings.redis.socket_connect_timeout,
            retry_on_timeout=settings.redis.retry_on_timeout,
            logger=stream_logger,
        )

    def add_kafka_broker(self):
        self.kafka_broker = KafkaBroker(settings.queue.bootstrap_servers)

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
        delay: Optional[timedelta] = None,
        scheduler: Optional[str] = None,
        max_length: Optional[int] = settings.redis.max_stream_size,
    ):
        """
        Публикует сообщение в Redis сразу, с задержкой или по расписанию.
        """
        if self.redis_broker is None:
            raise ValueError("Redis broker is not initialized")

        if delay and scheduler:
            raise ValueError("Cannot use both delay and scheduler")

        headers = {}
        if max_length is not None:
            headers["X-STREAM-MAXLEN"] = str(max_length)

        handle_message = {"data": message}

        # Если нет расписания - публикуем сразу
        if not delay and not scheduler:
            await self.redis_broker.publish(
                handle_message,
                stream=stream,
                headers=headers,
                maxlen=max_length,
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
            self._execute_redis_publish,
            trigger=trigger,
            args=(stream, handle_message, headers, max_length),
            id=job_id,
            replace_existing=True,
        )

    async def _execute_redis_publish(
        self,
        stream: str,
        message: Dict[str, Any],
        headers: Dict[str, str],
        max_length: Optional[int],
    ):
        """Вспомогательный метод для выполнения отложенной публикации"""
        await self.redis_broker.publish(
            message,
            stream=stream,
            headers=headers,
            maxlen=max_length,
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
