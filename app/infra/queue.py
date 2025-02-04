from typing import Dict, List, Optional

import asyncio
from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from app.config.settings import settings
from app.utils.logging_service import queue_logger


__all__ = (
    "QueueClient",
    "queue_client",
)


class QueueClient:
    """Manages Kafka infrastructure including connections, topics creation, and health checks.

    Responsibilities:
    - Connection lifecycle management (producer, consumer, admin)
    - Topic creation and configuration
    - Health monitoring of Kafka components
    - Resource cleanup
    """

    def __init__(self, settings):
        self.logger = queue_logger
        self.settings = settings
        self._producer: Optional[Producer] = None
        self._consumer: Optional[Consumer] = None
        self._admin: Optional[AdminClient] = None

    async def initialize(self) -> None:
        """Establish connections to Kafka cluster and initialize clients."""
        config = self.settings.get_kafka_config()

        try:
            # Initialize admin client synchronously as it's lightweight
            self._admin = AdminClient(config)

            # Initialize producer and consumer with async wrapper
            self._producer = await self._create_async_producer(config)
            self._consumer = await self._create_async_consumer(config)

            self.logger.info("Kafka connections established")
        except Exception:
            self.logger.critical("Kafka initialization failed", exc_info=True)
            raise

    async def _create_async_producer(self, config: Dict) -> Producer:
        """Async wrapper for synchronous producer creation with configuration"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: Producer(
                {
                    **config,
                    "acks": self.settings.producer_acks,
                    "linger.ms": self.settings.producer_linger_ms,
                }
            ),
        )

    async def _create_async_consumer(self, config: Dict) -> Consumer:
        """Async wrapper for synchronous consumer creation with configuration"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: Consumer(
                {
                    **config,
                    "group.id": self.settings.consumer_group,
                    "auto.offset.reset": self.settings.auto_offset_reset,
                    "max.poll.records": self.settings.max_poll_records,
                }
            ),
        )

    async def create_topics(
        self,
        topics: List[str],
        num_partitions: int = 3,
        replication_factor: int = 2,
    ) -> None:
        """Create Kafka topics with specified partitioning and replication."""
        new_topics = [
            NewTopic(topic, num_partitions, replication_factor)
            for topic in topics
        ]

        try:
            # AdminClient operations are synchronous
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self._admin.create_topics(new_topics)
            )
            self.logger.info(f"Created topics: {', '.join(topics)}")
        except Exception:
            self.logger.error("Topic creation failed", exc_info=True)
            raise

    async def close(self) -> None:
        """Gracefully terminate all Kafka connections and flush pending messages."""
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
        self.logger.info("Kafka connections closed")

    @property
    def producer(self) -> Producer:
        """Get thread-safe producer instance for message production."""
        if not self._producer:
            raise RuntimeError("Producer not initialized")
        return self._producer

    @property
    def consumer(self) -> Consumer:
        """Get configured consumer instance for message consumption."""
        if not self._consumer:
            raise RuntimeError("Consumer not initialized")
        return self._consumer

    async def check_health(self) -> Dict[str, bool]:
        """Check connectivity status of all Kafka components."""
        return {
            "admin": await self._check_admin_health(),
            "producer": await self._check_producer_health(),
            "consumer": await self._check_consumer_health(),
        }

    async def _check_admin_health(self, timeout: float = 0.5) -> bool:
        """Verify admin client connectivity by listing topics."""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self._admin.list_topics(timeout=timeout)
            )
            return True
        except Exception:
            return False

    async def _check_producer_health(self, timeout: float = 0.5) -> bool:
        """Verify producer functionality through buffer flush."""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self.producer.flush(timeout=timeout)
            )
            return True
        except Exception:
            return False

    async def _check_consumer_health(self, timeout: float = 0.5) -> bool:
        """Verify consumer connectivity by listing topics."""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self.consumer.list_topics(timeout=timeout)
            )
            return True
        except Exception:
            return False


queue_client = QueueClient(settings=settings.queue)
