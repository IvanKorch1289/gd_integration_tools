from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional
from uuid import uuid4

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from faststream import BaseMiddleware, ExceptionMiddleware, FastStream
from faststream.broker.message import StreamMessage
from faststream.security import BaseSecurity

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
        self.rabbit_settings = settings.queue
        self.rabbit_broker = None
        self.redis_router = None
        self.rabbitmq_router = None
        self.scheduler = scheduler_manager.scheduler
        self._initialize_routers()

    def _initialize_routers(self):
        """Set up Redis and RabbitMQ routers with configuration."""
        self._setup_redis_router()
        self._setup_rabbit_router()

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
                MessageLoggingMiddleware,
                ExceptionMiddleware(
                    handlers={
                        Exception: lambda exc: stream_logger.error(
                            f"Exception: {exc}", exc_info=True
                        )
                    }
                ),
            ],
        )

    def _setup_rabbit_router(self):
        """Configure RabbitMQ router with settings from configuration."""
        from faststream.rabbit.fastapi import RabbitRouter

        self.rabbit_router = RabbitRouter(
            url=self.rabbit_settings.queue_url,
            security=BaseSecurity(
                use_ssl=self.rabbit_settings.use_ssl,
                # ssl_context=None,
            ),
            timeout=self.rabbit_settings.timeout,
            reconnect_interval=self.rabbit_settings.reconnect_interval,
            max_consumers=self.rabbit_settings.max_consumers,
            graceful_timeout=self.rabbit_settings.graceful_timeout,
            schema_url="/asyncapi",
            asyncapi_tags=[{"name": "rabbitmq"}],
            include_in_schema=True,
            middlewares=[
                MessageLoggingMiddleware,
                ExceptionMiddleware(
                    handlers={
                        Exception: lambda exc: stream_logger.error(
                            f"Exception: {exc}", exc_info=True
                        )
                    }
                ),
            ],
        )

    async def publish_to_rabbit(
        self,
        topic: str,
        message: Dict[str, Any],
        delay: Optional[timedelta] = None,
        scheduler: Optional[str] = None,
    ):
        """
        Publish a message to RabbitMQ either immediately, with delay, or on schedule.

        Args:
            topic: Target RabbitMQ topic
            message: Message content as dictionary
            key: Optional message key
            partition: Optional target partition
            delay: Optional timedelta for delayed publishing
            scheduler: Optional cron schedule string

        Raises:
            ValueError: If both delay and scheduler are specified
        """
        if self.rabbit_router is None:
            raise ValueError("RabbitMQ router is not initialized")

        self._validate_scheduling_params(delay, scheduler)

        if not delay and not scheduler:
            await self._publish_rabbit_immediately(topic, message)
        else:
            self._schedule_publish(
                delay=delay,
                scheduler=scheduler,
                publish_func=self._execute_rabbit_publish,
                func_kwargs={
                    "topic": topic,
                    "message": message,
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

    async def _publish_rabbit_immediately(
        self,
        topic: str,
        message: Dict[str, Any],
        key: Optional[str],
        partition: Optional[int],
    ):
        """Immediately publish message to RabbitMQ."""
        await self.rabbit_router.broker.publish(
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

    async def _execute_rabbit_publish(
        self,
        topic: str,
        message: Dict[str, Any],
        key: Optional[str],
        partition: Optional[int],
    ):
        """Execute scheduled Kafka publish operation."""
        await self.rabbit_router.broker.publish(
            message=message,
            topic=topic,
            key=key,
            partition=partition,
        )


stream_client = StreamClient()
