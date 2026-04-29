from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
from uuid import uuid4

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from faststream import BaseMiddleware, ExceptionMiddleware, FastStream
from faststream.message import StreamMessage
from faststream.security import BaseSecurity

from src.core.config.constants import consts
from src.core.config.settings import settings
from src.infrastructure.external_apis.logging_service import stream_logger
from src.infrastructure.resilience.breaker import BreakerSpec, breaker_registry

__all__ = ("stream_client", "StreamClient", "get_stream_client")


def _safe_repr_message(payload: Any, limit: int = 500) -> str:
    text = repr(payload)
    return text[:limit] + ("..." if len(text) > limit else "")


class MessageLoggingMiddleware(BaseMiddleware):
    """Осторожное логирование сообщений без избыточного payload leakage."""

    async def consume_scope(
        self, call_next: Callable[[Any], Awaitable[Any]], msg: StreamMessage[Any]
    ) -> Any:
        stream_logger.info(
            "Получено сообщение id=%s correlation_id=%s",
            getattr(msg, "message_id", None),
            getattr(msg, "correlation_id", None),
        )
        return await call_next(msg)

    async def publish_scope(
        self, call_next: Callable[..., Awaitable[Any]], msg: Any, **options: Any
    ) -> Any:
        stream_logger.info(
            "Публикация сообщения payload=%s options=%s",
            _safe_repr_message(msg),
            _safe_repr_message(options),
        )
        return await call_next(msg, **options)


class StreamClient:
    """Управление Redis/Rabbit/Kafka брокерами и отложенной публикацией.

    IL2.1 (ADR-013): Kafka теперь унифицирован через FastStream KafkaRouter
    (ранее — прямой aiokafka в `messaging/kafka.py`). Прямой aiokafka клиент
    остаётся как shim до H3_PLUS с DeprecationWarning — см. соответствующий
    модуль.
    """

    def __init__(self) -> None:
        from src.infrastructure.scheduler.scheduler_manager import scheduler_manager

        self.stream_app = FastStream(logger=stream_logger)
        self.redis_settings = settings.redis
        self.rabbit_settings = settings.queue
        # Kafka-настройки: используем те же bootstrap_servers / group_id, что
        # и legacy aiokafka-клиент — для плавной миграции.
        self.kafka_settings = getattr(settings, "kafka", None)
        self.scheduler = scheduler_manager.scheduler

        self.redis_router = None
        self.rabbit_router = None
        self.kafka_router = None

        self._initialize_routers()

    def _initialize_routers(self) -> None:
        self._setup_redis_router()
        self._setup_rabbit_router()
        self._setup_kafka_router()

    def _common_middlewares(self) -> list[Any]:
        return [
            MessageLoggingMiddleware,
            ExceptionMiddleware(handlers={Exception: self._log_middleware_exception}),
        ]

    @staticmethod
    async def _log_middleware_exception(exc: Exception) -> None:
        stream_logger.error("Ошибка брокера: %s", str(exc), exc_info=True)

    def _setup_redis_router(self) -> None:
        from faststream.redis.fastapi import RedisRouter

        redis_url = f"{self.redis_settings.redis_url}/{self.redis_settings.db_queue}"

        self.redis_router = RedisRouter(
            url=redis_url,
            max_connections=self.redis_settings.max_connections,
            socket_timeout=self.redis_settings.socket_timeout,
            socket_connect_timeout=self.redis_settings.socket_connect_timeout,
            retry_on_timeout=self.redis_settings.retry_on_timeout,
            logger=stream_logger,
            db=self.redis_settings.db_queue,
            schema_url="/asyncapi",
            asyncapi_tags=[{"name": "redis"}],
            include_in_schema=True,
            middlewares=self._common_middlewares(),
        )

    def _setup_rabbit_router(self) -> None:
        from faststream.rabbit.fastapi import RabbitRouter

        self.rabbit_router = RabbitRouter(
            url=self.rabbit_settings.queue_url,
            security=BaseSecurity(use_ssl=self.rabbit_settings.use_ssl),
            timeout=self.rabbit_settings.timeout,
            reconnect_interval=self.rabbit_settings.reconnect_interval,
            max_consumers=self.rabbit_settings.max_consumers,
            graceful_timeout=self.rabbit_settings.graceful_timeout,
            schema_url="/asyncapi",
            asyncapi_tags=[{"name": "rabbitmq"}],
            include_in_schema=True,
            middlewares=self._common_middlewares(),
        )

    def _setup_kafka_router(self) -> None:
        """IL2.1: унификация Kafka через FastStream (ADR-013).

        Идёт параллельно с legacy прямым aiokafka клиентом
        (`messaging/kafka.py`). Миграция существующих call-site-ов —
        следующий шаг (migration-guide в ADR-013).

        Если `settings.kafka` не определён — роутер не инициализируется
        (kafka-функционал опционален в текущих stage-окружениях).
        """
        if self.kafka_settings is None:
            stream_logger.debug(
                "kafka settings not found — Kafka router skipped "
                "(IL2.1 miграция не ломает стенды без Kafka)"
            )
            return
        try:
            from faststream.kafka.fastapi import KafkaRouter
        except ImportError as exc:
            stream_logger.warning(
                "faststream[kafka] not installed — Kafka router skipped: %s", exc
            )
            return

        bootstrap = getattr(self.kafka_settings, "bootstrap_servers", "localhost:9092")
        self.kafka_router = KafkaRouter(
            bootstrap_servers=bootstrap,
            logger=stream_logger,
            schema_url="/asyncapi",
            asyncapi_tags=[{"name": "kafka"}],
            include_in_schema=True,
            middlewares=self._common_middlewares(),
            # IL1.5: idempotent producer унаследован — FastStream сам
            # конфигурирует aiokafka с enable_idempotence=True + acks="all",
            # если в producer-config задан transactional_id или при явном
            # указании `publisher(..., idempotent=True)`.
        )

    @staticmethod
    def _validate_schedule_args(delay: timedelta | None, cron: str | None) -> None:
        if delay and cron:
            raise ValueError("Нельзя одновременно использовать delay и cron")

    def _build_trigger(
        self, delay: timedelta | None, cron: str | None
    ) -> DateTrigger | CronTrigger:
        if delay:
            return DateTrigger(run_date=datetime.now(consts.MOSCOW_TZ) + delay)

        if cron is None:
            raise ValueError("cron must be provided when delay is None")

        return CronTrigger.from_crontab(cron, timezone=consts.MOSCOW_TZ)

    def _schedule_publish(
        self,
        delay: timedelta | None,
        cron: str | None,
        publish_func: Callable[..., Awaitable[None]],
        func_kwargs: dict[str, Any],
    ) -> str:
        job_id = f"scheduled_publish_{uuid4()}"
        trigger = self._build_trigger(delay, cron)

        self.scheduler.add_job(
            publish_func,
            trigger=trigger,
            kwargs=func_kwargs,
            id=job_id,
            replace_existing=False,
            executor="async",
            jobstore="backup",
        )
        return job_id

    async def publish_to_rabbit(
        self,
        queue: str,
        message: dict[str, Any],
        delay: timedelta | None = None,
        cron: str | None = None,
    ) -> str | None:
        if self.rabbit_router is None:
            raise RuntimeError("Rabbit router не инициализирован")

        self._validate_schedule_args(delay, cron)

        if not delay and not cron:
            await self._publish_rabbit_immediately(queue, message)
            return None

        return self._schedule_publish(
            delay=delay,
            cron=cron,
            publish_func=self._execute_rabbit_publish,
            func_kwargs={"queue": queue, "message": message},
        )

    async def publish_to_redis(
        self,
        stream: str,
        message: dict[str, Any],
        headers: dict[str, Any] | None = None,
        delay: timedelta | None = None,
        cron: str | None = None,
    ) -> str | None:
        if self.redis_router is None:
            raise RuntimeError("Redis router не инициализирован")

        self._validate_schedule_args(delay, cron)

        if not delay and not cron:
            await self._publish_redis_immediately(
                stream=stream, message=message, headers=headers or {}
            )
            return None

        return self._schedule_publish(
            delay=delay,
            cron=cron,
            publish_func=self._execute_redis_publish,
            func_kwargs={
                "stream": stream,
                "message": message,
                "headers": headers or {},
            },
        )

    async def _publish_rabbit_immediately(
        self, queue: str, message: dict[str, Any]
    ) -> None:
        # Wave 6.2: rabbit publish защищён CB через единый фасад.
        # Дефолты из BreakerSpec (consts.DEFAULT_CB_*).
        breaker = breaker_registry.get_or_create(
            "rabbit:publish", BreakerSpec()
        )
        async with breaker.guard():
            await self.rabbit_router.broker.publish(  # type: ignore
                message=message, queue=queue, mandatory=True
            )

    async def _publish_redis_immediately(
        self, stream: str, message: dict[str, Any], headers: dict[str, Any]
    ) -> None:
        await self.redis_router.broker.publish(  # type: ignore
            message=message, stream=stream, headers=headers
        )

    async def _execute_redis_publish(
        self, stream: str, message: dict[str, Any], headers: dict[str, Any]
    ) -> None:
        await self._publish_redis_immediately(stream, message, headers)

    async def _execute_rabbit_publish(
        self, queue: str, message: dict[str, Any]
    ) -> None:
        await self._publish_rabbit_immediately(queue, message)

    # -- Kafka API (IL2.1) ---------------------------------------------

    async def publish_to_kafka(
        self,
        topic: str,
        message: dict[str, Any],
        key: str | None = None,
        headers: dict[str, Any] | None = None,
        delay: timedelta | None = None,
        cron: str | None = None,
    ) -> str | None:
        """Публикация через FastStream KafkaRouter (унифицированный API).

        Поддерживает immediate + delayed (APScheduler) + cron-scheduled
        publishing — симметрично с Rabbit/Redis.
        """
        if self.kafka_router is None:
            raise RuntimeError(
                "Kafka router не инициализирован (settings.kafka отсутствует или "
                "faststream[kafka] не установлен)"
            )
        self._validate_schedule_args(delay, cron)
        if not delay and not cron:
            await self._publish_kafka_immediately(
                topic=topic, message=message, key=key, headers=headers or {}
            )
            return None
        return self._schedule_publish(
            delay=delay,
            cron=cron,
            publish_func=self._execute_kafka_publish,
            func_kwargs={
                "topic": topic,
                "message": message,
                "key": key,
                "headers": headers or {},
            },
        )

    async def _publish_kafka_immediately(
        self,
        topic: str,
        message: dict[str, Any],
        key: str | None,
        headers: dict[str, Any],
    ) -> None:
        await self.kafka_router.broker.publish(  # type: ignore[union-attr]
            message=message, topic=topic, key=key, headers=headers
        )

    async def _execute_kafka_publish(
        self,
        topic: str,
        message: dict[str, Any],
        key: str | None,
        headers: dict[str, Any],
    ) -> None:
        await self._publish_kafka_immediately(topic, message, key, headers)


_stream_client: StreamClient | None = None


def get_stream_client() -> StreamClient:
    global _stream_client
    if _stream_client is None:
        _stream_client = StreamClient()
    return _stream_client


stream_client = get_stream_client()
