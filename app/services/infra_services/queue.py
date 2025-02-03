import json
from collections import defaultdict
from typing import Any, Callable, Dict, Optional

import asyncio
from confluent_kafka import Message

from app.infra.queue import KafkaClient, kafka_client
from app.services.route_services.orders import get_order_service
from app.utils.logging_service import kafka_logger


__all__ = (
    "QueueService",
    "queue_service",
)


class QueueService:
    """
    Сервис для работы с Kafka: отправка/потребление сообщений, бизнес-логика
    """

    def __init__(self, client: KafkaClient, dlq_suffix: str = "_dlq"):
        self.client = client
        self.dlq_suffix = dlq_suffix
        self.handlers = defaultdict(list)
        self._consuming_tasks = []

    def subscribe(self, topic: str, handler: Callable[[Dict[str, Any]], None]):
        """Регистрация обработчиков для топика"""
        self.handlers[topic].append(handler)

    async def send(
        self,
        topic: str,
        payload: Dict[str, Any],
        key: Optional[str] = None,
        headers: Optional[Dict] = None,
    ) -> None:
        """Отправка сообщения с обработкой ошибок"""
        try:
            serialized = json.dumps(payload).encode("utf-8")
            await self.client._producer.produce(
                topic, key=key, value=serialized
            )
            kafka_logger.info(f"Sent to {topic}: {payload}")
        except Exception as e:
            kafka_logger.error(f"Failed to send to {topic}: {e}")
            await self._handle_dlq(topic, serialized, key)
            raise

    async def start_consumers(self):
        """Запуск потребителей для всех зарегистрированных топиков"""
        for topic in self.handlers.keys():
            task = asyncio.create_task(self._consume_topic(topic))
            self._consuming_tasks.append(task)

    async def _consume_topic(self, topic: str):
        """Потребление сообщений из указанного топика"""
        while True:
            try:
                message: Optional[
                    Message
                ] = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.client._consumer.poll(1.0)
                )

                if message is None:
                    continue

                if message.error():
                    kafka_logger.error(f"Consumer error: {message.error()}")
                    continue

                await self._process_message(message)
                await self.client._consumer.commit(message)

            except Exception as e:
                kafka_logger.error(f"Consuming failed: {e}")
                await self._handle_dlq(topic, message.value(), message.key())
                raise

    async def _process_message(self, message: Message):
        """Обработка одного сообщения"""
        try:
            payload = json.loads(message.value().decode("utf-8"))
            for handler in self.handlers[message.topic()]:
                if asyncio.iscoroutinefunction(handler):
                    await handler(payload)
                else:
                    await asyncio.get_event_loop().run_in_executor(
                        None, handler, payload
                    )
        except Exception as e:
            kafka_logger.error(f"Processing failed: {e}")
            await self._handle_dlq(
                message.topic(), message.value(), message.key()
            )
            raise

    async def _handle_dlq(
        self, original_topic: str, raw_message: bytes, key: Optional[str]
    ):
        """Обработка DLQ"""
        dlq_topic = f"{original_topic}{self.dlq_suffix}"
        await self.client._producer.produce(
            dlq_topic, key=key, value=raw_message
        )
        kafka_logger.info(f"Message forwarded to DLQ: {dlq_topic}")


queue_service = QueueService(client=kafka_client)

queue_service.subscribe("orders", get_order_service().add)
