from collections import defaultdict
from typing import Any, Callable, Dict, Optional

import asyncio
import json_tricks
from confluent_kafka import Message

from app.config.settings import settings
from app.infra.queue import QueueClient, queue_client
from app.utils.logging_service import queue_logger
from app.utils.utils import utilities


__all__ = (
    "QueueService",
    "queue_service",
)


class QueueService:
    """Handles message processing workflow and business logic.

    Responsibilities:
    - Message serialization/deserialization
    - Handler registration and execution
    - Consumption loop management
    - Error handling and DLQ management
    - Offset commit management
    """

    def __init__(
        self,
        client: QueueClient,
        dlq_suffix: str = "_dlq",
        max_processing_attempts: int = 3,
    ):
        self.logger = queue_logger
        self.client = client
        self.dlq_suffix = dlq_suffix
        self.max_processing_attempts = max_processing_attempts
        self.handlers = defaultdict(list)
        self._consumption_active = False

    def register_handler(
        self, topic: str, handler: Callable[[Dict[str, Any]], None]
    ) -> None:
        """Register message processor for specific topic."""
        self.handlers[topic].append(handler)
        self.logger.debug(f"Registered handler for {topic}")

    async def send_message(
        self,
        topic: str,
        payload: Dict[str, Any],
        key: Optional[str] = None,
        headers: Optional[Dict] = None,
    ) -> None:
        """Produce message to Kafka with JSON serialization and error handling."""
        try:
            serialized = json_tricks.dumps(
                payload, extra_obj_encoders=[utilities.custom_json_encoder]
            ).encode("utf-8")
            loop = asyncio.get_event_loop()

            await loop.run_in_executor(
                None,
                lambda: self.client.producer.produce(
                    topic, key=key, value=serialized, headers=headers
                ),
            )
            self.logger.debug(f"Produced message to {topic}")
        except Exception:
            self.logger.error("Message production failed", exc_info=True)
            await self._handle_dlq(topic, serialized, key)
            raise

    async def start_message_consumption(self) -> None:
        """Start continuous message consumption loop for registered topics."""
        self._consumption_active = True
        self.client.consumer.subscribe(list(self.handlers.keys()))
        self.logger.info(f"Started consuming from {len(self.handlers)} topics")

        while self._consumption_active:
            await self._process_message_batch()

    async def _process_message_batch(self) -> None:
        """Poll and process messages from Kafka with error handling."""
        try:
            loop = asyncio.get_event_loop()
            message = await loop.run_in_executor(
                None, lambda: self.client.consumer.poll(1.0)
            )

            if message is None:
                return

            if message.error():
                self.logger.error(f"Consumer error: {message.error()}")
                return

            await self._execute_handlers(message)
            await self._commit_processed_offset(message)

        except Exception:
            self.logger.error("Message processing failed", exc_info=True)
            await self._handle_dlq(
                message.topic(), message.value(), message.key()
            )

    async def _execute_handlers(self, message: Message) -> None:
        """Execute registered handlers for message with retry logic."""
        payload = json_tricks.loads(
            message.value().decode("utf-8"),
            extra_obj_pairs_hooks=[utilities.custom_json_decoder],
        )

        for attempt in range(1, self.max_processing_attempts + 1):
            try:
                for handler in self.handlers[message.topic()]:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(payload)
                    else:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, handler, payload)
                break
            except Exception:
                if attempt == self.max_processing_attempts:
                    raise
                self.logger.warning(f"Retrying handler (attempt {attempt})")

    async def _commit_processed_offset(self, message: Message) -> None:
        """Commit offset after successful message processing."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: self.client.consumer.commit(message)
        )
        self.logger.debug("Committed message offset")

    async def _handle_dlq(
        self, original_topic: str, raw_message: bytes, key: Optional[str]
    ) -> None:
        """Forward unprocessable messages to dedicated dead-letter queue."""
        dlq_topic = f"{original_topic}{self.dlq_suffix}"
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.client.producer.produce(
                    dlq_topic, key=key, value=raw_message
                ),
            )
            self.logger.info(f"Forwarded to DLQ: {dlq_topic}")
        except Exception:
            self.logger.critical("DLQ handling failed", exc_info=True)
            raise

    async def stop_message_consumption(self) -> None:
        """Gracefully stop message consumption loop."""
        self._consumption_active = False
        await self.client.close()
        self.logger.info("Stopped message consumption")


queue_service = QueueService(
    client=queue_client,
    dlq_suffix=settings.queue.dlq_suffix,
    max_processing_attempts=settings.queue.max_processing_attempts,
)
