"""Kafka producer/consumer на базе aiokafka.

Предоставляет async API для публикации и потребления
сообщений из Apache Kafka с DSL-интеграцией.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from app.core.errors import ServiceError

__all__ = ("BaseKafkaClient", "KafkaClient", "get_kafka_client")

logger = logging.getLogger(__name__)


class BaseKafkaClient(ABC):
    """Абстрактный базовый класс для Kafka-клиентов."""

    @abstractmethod
    async def produce(
        self,
        topic: str,
        value: bytes,
        key: bytes | None = None,
        headers: list[tuple[str, bytes]] | None = None,
    ) -> None:
        """Отправляет сообщение в топик."""

    @abstractmethod
    async def consume_one(self, timeout_ms: int = 1000) -> Any:
        """Получает одно сообщение."""

    @abstractmethod
    async def close(self) -> None:
        """Закрывает producer и consumer."""


class KafkaClient(BaseKafkaClient):
    """Асинхронный Kafka-клиент (producer + consumer).

    Attrs:
        bootstrap_servers: Адрес(а) Kafka-брокеров.
        group_id: ID группы потребителей.
    """

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        group_id: str = "gd-integration-tools",
    ) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self._producer: Any = None
        self._consumer: Any = None

    async def start_producer(self) -> None:
        """Запускает Kafka producer."""
        from aiokafka import AIOKafkaProducer

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            linger_ms=10,
            batch_size=32768,
            compression_type="snappy",
        )
        await self._producer.start()
        logger.info("Kafka producer запущен: %s", self.bootstrap_servers)

    async def stop_producer(self) -> None:
        """Останавливает Kafka producer."""
        if self._producer:
            await self._producer.stop()
            self._producer = None

    async def produce(
        self,
        topic: str,
        value: bytes,
        key: bytes | None = None,
        headers: list[tuple[str, bytes]] | None = None,
    ) -> None:
        """Отправляет сообщение в Kafka-топик.

        Args:
            topic: Имя топика.
            value: Тело сообщения (bytes).
            key: Ключ партиционирования (опционально).
            headers: Заголовки сообщения (опционально).

        Raises:
            ServiceError: Если producer не запущен.
        """
        if self._producer is None:
            raise ServiceError(detail="Kafka producer не запущен")

        await self._producer.send_and_wait(
            topic,
            value=value,
            key=key,
            headers=headers,
        )
        logger.debug("Kafka: отправлено в %s", topic)

    async def produce_fire_and_forget(
        self,
        topic: str,
        value: bytes,
        key: bytes | None = None,
    ) -> None:
        """Отправляет без ожидания ACK (максимальный throughput)."""
        if self._producer is None:
            raise ServiceError(detail="Kafka producer не запущен")
        await self._producer.send(topic, value=value, key=key)

    async def produce_json(
        self,
        topic: str,
        data: dict[str, Any],
        key: str | None = None,
    ) -> None:
        """Отправляет JSON-сообщение в Kafka-топик.

        Args:
            topic: Имя топика.
            data: Данные для сериализации в JSON.
            key: Ключ партиционирования (строка).
        """
        import orjson

        value = orjson.dumps(data)
        key_bytes = key.encode() if key else None
        await self.produce(topic, value=value, key=key_bytes)

    async def start_consumer(
        self, *topics: str
    ) -> None:
        """Запускает Kafka consumer.

        Args:
            *topics: Топики для подписки.
        """
        from aiokafka import AIOKafkaConsumer

        self._consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
        )
        await self._consumer.start()
        logger.info(
            "Kafka consumer запущен: topics=%s, group=%s",
            topics,
            self.group_id,
        )

    async def stop_consumer(self) -> None:
        """Останавливает Kafka consumer."""
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None

    async def consume_one(self, timeout_ms: int = 1000) -> Any:
        """Получает одно сообщение из Kafka.

        Args:
            timeout_ms: Таймаут ожидания (мс).

        Returns:
            ConsumerRecord или ``None``.
        """
        if self._consumer is None:
            return None

        records = await self._consumer.getmany(
            timeout_ms=timeout_ms, max_records=1
        )
        for tp_records in records.values():
            if tp_records:
                return tp_records[0]
        return None

    async def close(self) -> None:
        """Останавливает producer и consumer."""
        await self.stop_producer()
        await self.stop_consumer()


from app.core.di import app_state_singleton


@app_state_singleton("kafka_client", KafkaClient)
def get_kafka_client() -> KafkaClient:
    """Возвращает KafkaClient из app.state или lazy-init fallback."""
