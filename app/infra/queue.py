from typing import Any, Dict, Optional

import asyncio
from confluent_kafka import AdminClient, Consumer, NewTopic, Producer

from app.config.settings import settings
from app.utils.logging import kafka_logger


__all__ = (
    "KafkaClient",
    "kafka_client",
)


class KafkaClient:
    """
    Управление инфраструктурой Kafka: подключения, топики, health checks
    """

    def __init__(self, settings):
        self.settings = settings
        self._producer: Optional[Producer] = None
        self._consumer: Optional[Consumer] = None
        self._admin: Optional[AdminClient] = None

    async def initialize(self):
        """Инициализация соединений"""
        config = self.settings.get_kafka_config()

        self._admin = AdminClient(config)
        self._producer = await self._create_producer(config)
        self._consumer = await self._create_consumer(config)

        kafka_logger.info("Kafka connections established")

    async def _create_producer(self, config: Dict) -> Producer:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: Producer(
                {
                    **config,
                    "acks": self.settings.queue_producer_acks,
                    "linger.ms": self.settings.queue_producer_linger_ms,
                }
            ),
        )

    async def _create_consumer(self, config: Dict) -> Consumer:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: Consumer(
                {
                    **config,
                    "group.id": self.settings.queue_consumer_group,
                    "auto.offset.reset": self.settings.queue_auto_offset_reset,
                }
            ),
        )

    async def create_topics(
        self,
        topics: list[str],
        num_partitions: int = 3,
        replication_factor: int = 2,
    ):
        """Создание топиков"""
        new_topics = [
            NewTopic(topic, num_partitions, replication_factor)
            for topic in topics
        ]
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: self._admin.create_topics(new_topics)
        )

    async def close(self):
        """Корректное завершение соединений"""
        tasks = []
        if self._producer:
            tasks.append(
                asyncio.get_event_loop().run_in_executor(
                    None, self._producer.flush
                )
            )
        if self._consumer:
            tasks.append(
                asyncio.get_event_loop().run_in_executor(
                    None, self._consumer.close
                )
            )
        await asyncio.gather(*tasks)

    async def check_admin_health(self, timeout: float = 0.5) -> bool:
        """Check admin client connectivity"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self._admin.list_topics(timeout=timeout)
            )
            return True
        except Exception as exc:
            kafka_logger.error(f"Admin healthcheck failed: {str(exc)}")
            return False

    async def check_producer_health(self, timeout: float = 0.5) -> bool:
        """Check producer connectivity"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self._producer.flush(timeout=timeout)
            )
            return True
        except Exception as exc:
            kafka_logger.error(f"Producer healthcheck failed: {str(exc)}")
            return False

    async def check_consumer_health(self, timeout: float = 0.5) -> bool:
        """Check consumer connectivity"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self._consumer.list_topics(timeout=timeout)
            )
            return True
        except Exception as exc:
            kafka_logger.error(f"Consumer healthcheck failed: {str(exc)}")
            return False

    async def healthcheck(self) -> bool:
        """
        Comprehensive health check for Kafka cluster

        Returns:
            {
                "status": "healthy"/"degraded"/"unhealthy",
                "details": {
                    "admin": bool,
                    "producer": bool,
                    "consumer": bool
                }
            }
        """
        checks = {
            "admin": await self.check_admin_health(),
            "producer": await self.check_producer_health(),
            "consumer": await self.check_consumer_health(),
        }

        if any(checks.values()):
            raise ConnectionError(f"Kafka connection check failed: {checks}")

        return True


kafka_client = KafkaClient(settings=settings.queue)
