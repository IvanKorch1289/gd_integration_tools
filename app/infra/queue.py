from typing import Dict, Optional

import asyncio
from confluent_kafka import AdminClient, Consumer, NewTopic, Producer

from app.config.settings import settings
from app.utils.logging import kafka_logger


__all__ = (
    "kafka_client",
    "KafkaClient",
)


class KafkaClient:
    """
    Управление подключениями и инфраструктурой Kafka

    Args:
        settings: Настройки из класса QueueSettings
    """

    def __init__(self, settings):
        self.settings = settings
        self._producer: Optional[Producer] = None
        self._consumer: Optional[Consumer] = None
        self._admin: Optional[AdminClient] = None

    async def initialize(self):
        """Инициализация подключений при старте приложения"""
        config = self.settings.get_kafka_config()

        # Создание административного клиента
        self._admin = AdminClient(config)

        # Инициализация продюсера
        self._producer = await self._create_producer(config)

        # Инициализация консьюмера
        self._consumer = await self._create_consumer(config)

        kafka_logger.info("Kafka connection start successfully")

    async def _create_producer(self, config: Dict) -> Producer:
        """Создание асинхронного продюсера"""
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
        """Создание асинхронного консьюмера"""
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

    async def create_topic(
        self,
        topic: str,
        num_partitions: int = 3,
        replication_factor: int = 2,
        dlq_suffix: str = "_dlq",
    ) -> None:
        """Создание топика с DLQ"""
        topics = [
            NewTopic(topic, num_partitions, replication_factor),
            NewTopic(
                f"{topic}{dlq_suffix}", num_partitions, replication_factor
            ),
        ]

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: self._admin.create_topics(topics)
        )
        kafka_logger.info(f"Topic '{topic}' created successfully")

    async def close(self):
        """Закрытие подключений при завершении работы"""
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
        kafka_logger.info("Kafka connection closed successfully")


kafka_client = KafkaClient(settings=settings.queue)
