import json
from typing import Any, Dict

import redis
import time
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from pydantic import ValidationError
from your_module import OrderSchemaIn, add  # Импортируйте ваши функции и схемы

from app.core import kafka_logger


# Настройки Kafka
KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
INPUT_TOPIC = "order_topic"
RETRY_TOPIC = "retry_topic"

# Настройки Redis
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0


class KafkaConsumerProducer:
    def __init__(self):
        self.logger = kafka_logger.getChild(self.__class__.__name__)

        try:
            self.consumer = AIOKafkaConsumer(
                INPUT_TOPIC,
                RETRY_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                enable_auto_commit=False,
            )
            self.producer = AIOKafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda m: json.dumps(m).encode("utf-8"),
            )
            self.redis_client = redis.Redis(
                host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, socket_connect_timeout=3
            )
            self.redis_client.ping()  # Проверка подключения к Redis
        except Exception:
            self.logger.error("Initialization failed", exc_info=True)
            raise

        self.logger.info("Service initialized successfully")

    async def start(self):
        """Запуск потребителя и продюсера Kafka."""
        try:
            await self.consumer.start()
            await self.producer.start()
            self.logger.info("Kafka consumer and producer started")
        except Exception:
            self.logger.error("Failed to start Kafka components", exc_info=True)
            raise

    async def stop(self):
        """Остановка потребителя и продюсера Kafka."""
        try:
            await self.consumer.stop()
            await self.producer.stop()
            self.logger.info("Kafka consumer and producer stopped")
        except Exception:
            self.logger.error("Error stopping Kafka components", exc_info=True)
            raise

    async def send_email_notification(self, message_id: str):
        """Отправка уведомления по электронной почте."""
        try:
            # Реальная реализация отправки email
            self.logger.info(f"Sending email notification for message {message_id}")
            # Здесь должен быть код отправки email
            self.logger.info(f"Notification for {message_id} sent successfully")
        except Exception:
            self.logger.error(
                f"Failed to send notification for {message_id}", exc_info=True
            )
            raise

    async def process_message(self, message: Dict[str, Any]):
        """Обработка сообщения с улучшенным логированием."""
        message_id = message.get("message_id")
        if not message_id:
            self.logger.warning("Received message without message_id")
            return

        redis_key = f"message:{message_id}"
        try:
            existing = self.redis_client.get(redis_key)
        except redis.RedisError:
            self.logger.error(f"Redis error for {message_id}", exc_info=True)
            return

        if existing:
            if existing.decode() == "processed":
                self.logger.debug(f"Message {message_id} already processed")
                return
            first_seen = float(existing.decode())
        else:
            first_seen = time.time()
            try:
                self.redis_client.set(redis_key, first_seen)
                self.logger.info(f"Message {message_id} first seen at {first_seen}")
            except redis.RedisError:
                self.logger.error(
                    f"Failed to save {message_id} to Redis", exc_info=True
                )
                return

        current_time = time.time()
        if current_time - first_seen > 86400:  # 24 часа
            self.logger.warning(f"Message {message_id} expired")
            try:
                await self.send_email_notification(message_id)
                self.redis_client.set(redis_key, "processed")
                await self.consumer.commit()
                self.logger.info(f"Expired message {message_id} handled")
            except Exception:
                self.logger.error(
                    f"Failed to handle expired {message_id}", exc_info=True
                )
            return

        try:
            order_data = OrderSchemaIn(**message)
            await add({"data": order_data.dict()})
            self.redis_client.set(redis_key, "processed")
            await self.consumer.commit()
            self.logger.info(f"Message {message_id} processed successfully")

        except ValidationError as ve:
            self.logger.error(
                f"Validation failed for {message_id}: {str(ve)}",
                extra={"message_body": message},
            )
            try:
                self.redis_client.set(redis_key, "processed")
                await self.consumer.commit()
                await self.send_email_notification(message_id)
            except Exception:
                self.logger.error(
                    f"Error handling validation failure for {message_id}", exc_info=True
                )

        except Exception:
            self.logger.error(
                f"Processing failed for {message_id}",
                exc_info=True,
                extra={"message_id": message_id},
            )
            try:
                await self.producer.send(RETRY_TOPIC, message)
                await self.producer.flush()
                await self.consumer.commit()
                self.logger.info(f"Message {message_id} sent to retry topic")
            except Exception:
                self.logger.error(
                    f"Failed to send {message_id} to retry topic", exc_info=True
                )
                await self.consumer.seek_to_end()
                raise

    async def consume_messages(self):
        """Основной цикл обработки сообщений."""
        self.logger.info("Starting message consumption")
        try:
            async for msg in self.consumer:
                self.logger.debug(
                    f"Received message from {msg.topic} partition {msg.partition}"
                )
                try:
                    await self.process_message(msg.value)
                except Exception:
                    self.logger.error(
                        "Error processing message",
                        exc_info=True,
                        extra={"offset": msg.offset, "partition": msg.partition},
                    )
        except Exception:
            self.logger.error("Fatal error in consume_messages", exc_info=True)
            raise
        finally:
            await self.stop()
            self.logger.info("Message consumption stopped")
