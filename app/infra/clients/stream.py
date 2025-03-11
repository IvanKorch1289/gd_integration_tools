from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, Optional
from uuid import uuid4

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from faststream import BaseMiddleware, ExceptionMiddleware, FastStream
from faststream.broker.message import StreamMessage
from faststream.security import BaseSecurity

from app.config.constants import consts
from app.config.settings import settings
from app.utils.logging_service import stream_logger


__all__ = (
    "stream_client",
    "StreamClient",
)


class MessageLoggingMiddleware(BaseMiddleware):
    """Middleware для логирования входящих и исходящих сообщений в потоке."""

    async def consume_scope(
        self,
        call_next: Callable[[Any], Awaitable[Any]],
        msg: StreamMessage[Any],
    ) -> Any:
        """Логирует входящие сообщения перед обработкой."""
        stream_logger.info(f"Получено сообщение: {msg}")
        return await call_next(msg)

    async def publish_scope(
        self,
        call_next: Callable[..., Awaitable[Any]],
        msg: Any,
        **options: Any,
    ) -> Any:
        """Логирует исходящие сообщения перед отправкой."""
        stream_logger.info(f"Отправлено сообщение: {msg}, опции: {options}")
        return await call_next(msg, **options)


class StreamClient:
    """Клиент для управления подключениями к потокам и публикации сообщений."""

    def __init__(self):
        """Инициализирует клиент с роутерами и планировщиком."""
        from app.infra.scheduler.scheduler_manager import scheduler_manager

        self.stream_client = FastStream(logger=stream_logger)
        self.redis_settings = settings.redis
        self.rabbit_settings = settings.queue
        self.rabbit_broker = None
        self.redis_router = None
        self.rabbitmq_router = None
        self.scheduler = scheduler_manager.scheduler
        self._initialize_routers()

    def _initialize_routers(self):
        """Настраивает роутеры для Redis и RabbitMQ."""
        self._setup_redis_router()
        self._setup_rabbit_router()

    def _setup_redis_router(self):
        """Настраивает роутер для Redis с параметрами из конфигурации."""
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
                            f"Ошибка: {exc}", exc_info=True
                        )
                    }
                ),
            ],
        )

    def _setup_rabbit_router(self):
        """Настраивает роутер для RabbitMQ с параметрами из конфигурации."""
        from faststream.rabbit.fastapi import RabbitRouter

        self.rabbit_router = RabbitRouter(
            url=self.rabbit_settings.queue_url,
            security=BaseSecurity(
                use_ssl=self.rabbit_settings.use_ssl,
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
                            f"Ошибка: {exc}", exc_info=True
                        )
                    }
                ),
            ],
        )

    async def publish_to_rabbit(
        self,
        queue: str,
        message: Dict[str, Any],
        delay: Optional[timedelta] = None,
        scheduler: Optional[str] = None,
    ):
        """
        Публикует сообщение в RabbitMQ сразу, с задержкой или по расписанию.

        Args:
            queue: Очередь RabbitMQ для публикации.
            message: Содержимое сообщения в виде словаря.
            delay: Опциональная задержка перед публикацией.
            scheduler: Опциональное расписание в формате cron.

        Raises:
            ValueError: Если указаны и задержка, и расписание.
        """
        if self.rabbit_router is None:
            raise ValueError("Роутер RabbitMQ не инициализирован")

        self._validate_scheduling_params(delay, scheduler)

        if not delay and not scheduler:
            await self._publish_rabbit_immediately(queue, message)
        else:
            self._schedule_publish(
                delay=delay,
                scheduler=scheduler,
                publish_func=self._execute_rabbit_publish,
                func_kwargs={
                    "queue": queue,
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
        Публикует сообщение в Redis сразу, с задержкой или по расписанию.

        Args:
            stream: Поток Redis для публикации.
            message: Содержимое сообщения в виде словаря.
            headers: Опциональные заголовки сообщения.
            delay: Опциональная задержка перед публикацией.
            scheduler: Опциональное расписание в формате cron.

        Raises:
            ValueError: Если указаны и задержка, и расписание.
        """
        if self.redis_router is None:
            raise ValueError("Роутер Redis не инициализирован")

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
        """Проверяет параметры планирования."""
        if delay and scheduler:
            raise ValueError(
                "Нельзя использовать одновременно задержку и расписание"
            )

    async def _publish_rabbit_immediately(
        self,
        queue: str,
        message: Dict[str, Any],
    ):
        """Публикует сообщение в RabbitMQ немедленно."""
        await self.rabbit_router.broker.publish(
            message=message,
            queue=queue,
            mandatory=True,
        )

    async def _publish_redis_immediately(
        self, stream: str, message: Dict[str, Any], headers: Dict[str, Any]
    ):
        """Публикует сообщение в Redis немедленно."""
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
        """Планирует публикацию сообщения с использованием APScheduler."""
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
        """Создает триггер на основе параметров планирования."""
        if delay:
            return DateTrigger(run_date=datetime.now(consts.MOSCOW_TZ) + delay)
        return CronTrigger.from_crontab(scheduler, timezone=consts.MOSCOW_TZ)

    async def _execute_redis_publish(
        self, stream: str, message: Dict[str, Any], headers: Dict[str, Any]
    ):
        """Выполняет запланированную публикацию в Redis."""
        await self.redis_router.broker.publish(
            message=message,
            stream=stream,
            headers=headers,
        )

    async def _execute_rabbit_publish(
        self,
        queue: str,
        message: Dict[str, Any],
    ):
        """Выполняет запланированную публикацию в RabbitMQ."""
        await self.rabbit_router.broker.publish(
            message=message,
            queue=queue,
        )


# Экземпляр клиента для работы с потоками
stream_client = StreamClient()
