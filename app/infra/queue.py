from typing import Dict, List, Optional

import asyncio
from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from app.config.settings import settings
from app.utils.logging_service import kafka_logger


__all__ = (
    "KafkaClient",
    "kafka_client",
)


class KafkaClient:
    """
    Manages Kafka infrastructure: connections, topics, and health checks.
    """

    def __init__(self, settings):
        """
        Initializes the KafkaClient with the provided settings.

        Args:
            settings: Configuration settings for Kafka.
        """
        self.settings = settings
        self._producer: Optional[Producer] = None
        self._consumer: Optional[Consumer] = None
        self._admin: Optional[AdminClient] = None

    async def initialize(self):
        """
        Initializes Kafka connections (admin, producer, and consumer).
        """
        config = self.settings.get_kafka_config()

        try:
            self._admin = AdminClient(config)
            self._producer = await self._create_producer(
                config.get_kafka_producer_config()
            )
            self._consumer = await self._create_consumer(
                config.get_kafka_producer_config
            )
            kafka_logger.info("Kafka connections established")
        except Exception as e:
            kafka_logger.error(f"Failed to initialize Kafka connections: {e}")
            raise

    async def _create_producer(self, config: Dict) -> Producer:
        """
        Creates and returns a Kafka producer.

        Args:
            config: Configuration dictionary for the producer.

        Returns:
            Producer: Kafka producer instance.
        """
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
        """
        Creates and returns a Kafka consumer.

        Args:
            config: Configuration dictionary for the consumer.

        Returns:
            Consumer: Kafka consumer instance.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: Consumer(
                {
                    **config,
                    "group.id": self.settings.queue_consumer_group,
                    "auto.offset.reset": self.settings.queue_auto_offset_reset,
                    "max.poll.records": self.settings.queue_max_poll_records,  # Ensure this is correctly set
                }
            ),
        )

    async def create_topics(
        self,
        topics: List[str],
        num_partitions: int = 3,
        replication_factor: int = 2,
    ):
        """
        Creates Kafka topics.

        Args:
            topics: List of topic names to create.
            num_partitions: Number of partitions for each topic.
            replication_factor: Replication factor for each topic.
        """
        new_topics = [
            NewTopic(topic, num_partitions, replication_factor)
            for topic in topics
        ]
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None, lambda: self._admin.create_topics(new_topics)
            )
            kafka_logger.info(f"Topics created: {topics}")
        except Exception as e:
            kafka_logger.error(f"Failed to create topics: {e}")
            raise

    async def close(self):
        """
        Gracefully closes Kafka connections.
        """
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
        try:
            await asyncio.gather(*tasks)
            kafka_logger.info("Kafka connections closed")
        except Exception as e:
            kafka_logger.error(f"Failed to close Kafka connections: {e}")
            raise

    async def check_admin_health(self, timeout: float = 0.5) -> bool:
        """
        Checks the health of the Kafka admin client.

        Args:
            timeout: Timeout for the health check.

        Returns:
            bool: True if healthy, False otherwise.
        """
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self._admin.list_topics(timeout=timeout)
            )
            return True
        except Exception as e:
            kafka_logger.error(f"Admin healthcheck failed: {e}")
            return False

    async def check_producer_health(self, timeout: float = 0.5) -> bool:
        """
        Checks the health of the Kafka producer.

        Args:
            timeout: Timeout for the health check.

        Returns:
            bool: True if healthy, False otherwise.
        """
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self._producer.flush(timeout=timeout)
            )
            return True
        except Exception as e:
            kafka_logger.error(f"Producer healthcheck failed: {e}")
            return False

    async def check_consumer_health(self, timeout: float = 0.5) -> bool:
        """
        Checks the health of the Kafka consumer.

        Args:
            timeout: Timeout for the health check.

        Returns:
            bool: True if healthy, False otherwise.
        """
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self._consumer.list_topics(timeout=timeout)
            )
            return True
        except Exception as e:
            kafka_logger.error(f"Consumer healthcheck failed: {e}")
            return False

    async def healthcheck(self) -> Dict[str, str]:
        """
        Performs a comprehensive health check for the Kafka cluster.

        Returns:
            Dict[str, str]: A dictionary containing the overall status and details of each component.
        """
        checks = {
            "admin": await self.check_admin_health(),
            "producer": await self.check_producer_health(),
            "consumer": await self.check_consumer_health(),
        }

        status = (
            "healthy"
            if all(checks.values())
            else "degraded" if any(checks.values()) else "unhealthy"
        )

        return {"status": status, "details": checks}


kafka_client = KafkaClient(settings=settings.queue)
