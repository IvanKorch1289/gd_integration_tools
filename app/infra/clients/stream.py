from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional
from uuid import uuid4

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from faststream import BaseMiddleware, ExceptionMiddleware, FastStream
from faststream.broker.message import StreamMessage
from faststream.security import SASLPlaintext

from app.config.settings import settings
from app.utils.logging_service import stream_logger


__all__ = (
    "stream_client",
    "StreamClient",
)

# Timezone constant for scheduled jobs
MOSCOW_TZ = timezone(timedelta(hours=3))


class MessageLoggingMiddleware(BaseMiddleware):
    """Middleware to log incoming and outgoing stream messages."""

    async def consume_scope(
        self,
        call_next: Callable[[Any], Awaitable[Any]],
        msg: StreamMessage[Any],
    ) -> Any:
        """Log consumed messages before processing."""
        stream_logger.info(f"Subscribe: {msg}")
        return await call_next(msg)

    async def publish_scope(
        self,
        call_next: Callable[..., Awaitable[Any]],
        msg: Any,
        **options: Any,
    ) -> Any:
        """Log published messages before sending."""
        stream_logger.info(f"Publish: {msg}")
        return await call_next(msg, **options)


class StreamClient:
    """Client for managing stream connections and message publishing."""

    def __init__(self):
        """Initialize stream client with routers and scheduler."""
        from app.infra.application.scheduler import scheduler_manager

        self.stream_client = FastStream(logger=stream_logger)
        self.redis_settings = settings.redis
        self.kafka_settings = settings.queue
        self.kafka_broker = None
        self.redis_router = None
        self.kafka_router = None
        self.scheduler = scheduler_manager.scheduler
        self._initialize_routers()

    def _initialize_routers(self):
        """Set up Redis and Kafka routers with configuration."""
        self._setup_redis_router()
        self._setup_kafka_router()

    def _setup_redis_router(self):
        """Configure Redis router with settings from configuration."""
        from faststream.redis.fastapi import RedisRouter

        self.redis_router = RedisRouter(
            url=f"{self.redis_settings.redis_url}/{self.redis_settings.db_queue}",
            max_connections=self.redis_settings.max_connections,
            socket_timeout=self.redis_settings.socket_timeout,
            socket_connect_timeout=self.redis_settings.socket_connect_timeout,
            retry_on_timeout=self.redis_settings.retry_on_timeout,
            logger=stream_logger,
            db=self.redis_settings.db_queue,
            schema_url="/asyncapi",
            asyncapi_tags=[{"name": "redis"}],
            include_in_schema=True,
            middlewares=[
                ExceptionMiddleware(
                    handlers={
                        Exception: lambda exc: stream_logger.error(
                            "Exception", exc_info=True
                        )
                    }
                ),
                MessageLoggingMiddleware,
            ],
        )

    def _setup_kafka_router(self):
        """Configure Kafka router with settings from configuration."""
        from faststream.kafka.fastapi import KafkaRouter

        self.kafka_router = KafkaRouter(
            bootstrap_servers=self.kafka_settings.bootstrap_servers,
            # security=SASLPlaintext(
            #     use_ssl=False,
            #     ssl_context=None,
            #     username=self.kafka_settings.username,
            #     password=self.kafka_settings.password,
            # ),
            client_id=self.kafka_settings.client,
            request_timeout_ms=self.kafka_settings.request_timeout_ms,
            retry_backoff_ms=self.kafka_settings.retry_backoff_ms,
            metadata_max_age_ms=self.kafka_settings.metadata_max_age_ms,
            compression_type=self.kafka_settings.compression_type,
            enable_idempotence=self.kafka_settings.enable_idempotence,
            schema_url="/asyncapi",
            asyncapi_tags=[{"name": "kafka"}],
            include_in_schema=True,
            middlewares=[
                ExceptionMiddleware(
                    handlers={
                        Exception: lambda exc: stream_logger.error(
                            "Exception", exc_info=True
                        )
                    }
                ),
                MessageLoggingMiddleware,
            ],
        )

    async def publish_to_kafka(
        self,
        topic: str,
        message: Dict[str, Any],
        key: Optional[str] = None,
        partition: Optional[int] = None,
        delay: Optional[timedelta] = None,
        scheduler: Optional[str] = None,
    ):
        """
        Publish a message to Kafka either immediately, with delay, or on schedule.

        Args:
            topic: Target Kafka topic
            message: Message content as dictionary
            key: Optional message key
            partition: Optional target partition
            delay: Optional timedelta for delayed publishing
            scheduler: Optional cron schedule string

        Raises:
            ValueError: If both delay and scheduler are specified
        """
        if self.kafka_router is None:
            raise ValueError("Kafka router is not initialized")

        self._validate_scheduling_params(delay, scheduler)

        if not delay and not scheduler:
            await self._publish_kafka_immediately(
                topic, message, key, partition
            )
        else:
            self._schedule_publish(
                delay=delay,
                scheduler=scheduler,
                publish_func=self._execute_kafka_publish,
                func_kwargs={
                    "topic": topic,
                    "message": message,
                    "key": key,
                    "partition": partition,
                },
            )

    async def publish_to_redis(
        self,
        stream: str,
        message: Dict[str, Any],
        headers: Optional[Dict[str, Any]] = None,
        delay: Optional[timedelta] = None,
        scheduler: Optional[str] = None,
    ):
        """
        Publish a message to Redis either immediately, with delay, or on schedule.

        Args:
            stream: Target Redis stream
            message: Message content as dictionary
            headers: Optional message headers
            delay: Optional timedelta for delayed publishing
            scheduler: Optional cron schedule string

        Raises:
            ValueError: If both delay and scheduler are specified
        """
        if self.redis_router is None:
            raise ValueError("Redis router is not initialized")

        self._validate_scheduling_params(delay, scheduler)

        if not delay and not scheduler:
            await self._publish_redis_immediately(stream, message, headers)
        else:
            self._schedule_publish(
                delay=delay,
                scheduler=scheduler,
                publish_func=self._execute_redis_publish,
                func_kwargs={
                    "stream": stream,
                    "message": message,
                    "headers": headers or {},
                },
            )

    def _validate_scheduling_params(
        self, delay: Optional[timedelta], scheduler: Optional[str]
    ):
        """Validate scheduling parameters."""
        if delay and scheduler:
            raise ValueError("Cannot use both delay and scheduler")

    async def _publish_kafka_immediately(
        self,
        topic: str,
        message: Dict[str, Any],
        key: Optional[str],
        partition: Optional[int],
    ):
        """Immediately publish message to Kafka."""
        await self.kafka_router.broker.publish(
            message=message,
            topic=topic,
            key=key,
            partition=partition,
        )

    async def _publish_redis_immediately(
        self, stream: str, message: Dict[str, Any], headers: Dict[str, Any]
    ):
        """Immediately publish message to Redis."""
        await self.redis_router.broker.publish(
            message=message,
            stream=stream,
            headers=headers,
        )

    def _schedule_publish(
        self,
        delay: Optional[timedelta],
        scheduler: Optional[str],
        publish_func: Callable,
        func_kwargs: Dict[str, Any],
    ):
        """Schedule message publishing with APScheduler."""
        job_id = f"scheduled_job_{uuid4()}"
        trigger = self._create_trigger(delay, scheduler)

        self.scheduler.add_job(
            publish_func,
            trigger=trigger,
            kwargs=func_kwargs,
            id=job_id,
            replace_existing=True,
            remove_after_completion=True,
            executor="async",
            jobstore="backup",
        )

    def _create_trigger(
        self, delay: Optional[timedelta], scheduler: Optional[str]
    ) -> DateTrigger | CronTrigger:
        """Create appropriate trigger based on scheduling parameters."""
        if delay:
            return DateTrigger(run_date=datetime.now(MOSCOW_TZ) + delay)
        return CronTrigger.from_crontab(scheduler, timezone=MOSCOW_TZ)

    async def _execute_redis_publish(
        self, stream: str, message: Dict[str, Any], headers: Dict[str, Any]
    ):
        """Execute scheduled Redis publish operation."""
        await self.redis_router.broker.publish(
            message=message,
            stream=stream,
            headers=headers,
        )

    async def _execute_kafka_publish(
        self,
        topic: str,
        message: Dict[str, Any],
        key: Optional[str],
        partition: Optional[int],
    ):
        """Execute scheduled Kafka publish operation."""
        await self.kafka_router.broker.publish(
            message=message,
            topic=topic,
            key=key,
            partition=partition,
        )


stream_client = StreamClient()
