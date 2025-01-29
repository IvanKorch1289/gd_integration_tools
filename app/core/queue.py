# import json
# from abc import ABC, abstractmethod
# from typing import Any, Dict

# from aiokafka.producer import AIOKafkaProducer
# import redis
# import time
# from aiokafka.consumer import AIOKafkaConsumer
# from pydantic import ValidationError

# from your_module import OrderSchemaIn, add  # Импортируйте ваши функции и схемы
# from app.core import kafka_logger
# from app.core.settings import QueueSettings, settings


# class MessageBroker(ABC):
#     @abstractmethod
#     async def start(self):
#         pass

#     @abstractmethod
#     async def stop(self):
#         pass

#     @abstractmethod
#     async def consume_messages(self):
#         pass

#     @abstractmethod
#     async def send_retry(self, message: Dict[str, Any]):
#         pass


# class KafkaBroker(MessageBroker):
#     def __init__(self, settings: QueueSettings):
#         self.settings = settings
#         self.logger = kafka_logger.getChild("KafkaBroker")
#         self.consumer = None
#         self.producer = None

#     async def start(self):
#         consumer_args = {
#             "bootstrap_servers": self.settings.bootstrap_servers,
#             "group_id": self.settings.consumer_group,
#             "auto_offset_reset": self.settings.auto_offset_reset,
#             "enable_auto_commit": self.settings.enable_auto_commit,
#             "max_poll_records": self.settings.max_poll_records,
#             "max_poll_interval_ms": self.settings.max_poll_interval_ms,
#             "session_timeout_ms": self.settings.session_timeout_ms,
#             "security_protocol": self.settings.security_protocol,
#             "value_deserializer": lambda m: json.loads(m.decode("utf-8")),
#         }

#         if self.settings.sasl_mechanism:
#             consumer_args.update({
#                 "sasl_mechanism": self.settings.sasl_mechanism,
#                 "sasl_plain_username": self.settings.sasl_username,
#                 "sasl_plain_password": self.settings.sasl_password,
#             })

#         self.consumer = AIOKafkaConsumer(
#             self.settings.input_destination,
#             self.settings.retry_destination,
#             **consumer_args
#         )

#         producer_args = {
#             "bootstrap_servers": self.settings.bootstrap_servers,
#             "compression_type": self.settings.compression_type,
#             "acks": self.settings.producer_acks,
#             "retries": self.settings.producer_retries,
#             "linger_ms": self.settings.producer_linger_ms,
#             "value_serializer": lambda m: json.dumps(m).encode("utf-8"),
#             "security_protocol": self.settings.security_protocol,
#         }

#         if self.settings.sasl_mechanism:
#             producer_args.update({
#                 "sasl_mechanism": self.settings.sasl_mechanism,
#                 "sasl_plain_username": self.settings.sasl_username,
#                 "sasl_plain_password": self.settings.sasl_password,
#             })

#         self.producer = AIOKafkaProducer(**producer_args)

#         try:
#             await self.consumer.start()
#             await self.producer.start()
#             self.logger.info("Kafka broker started")
#         except Exception as e:
#             self.logger.error(f"Kafka startup failed: {str(e)}")
#             raise

#     async def stop(self):
#         try:
#             await self.consumer.stop()
#             await self.producer.stop()
#             self.logger.info("Kafka broker stopped")
#         except Exception as e:
#             self.logger.error(f"Kafka shutdown error: {str(e)}")
#             raise

#     async def consume_messages(self):
#         async for msg in self.consumer:
#             yield msg.value

#     async def send_retry(self, message: Dict[str, Any]):
#         await self.producer.send(self.settings.retry_destination, message)


# class QueueClient:
#     def __init__(self, broker: MessageBroker, redis_settings: RedisSettings):
#         self.broker = broker
#         self.logger = kafka_logger.getChild("QueueClient")
#         self.redis = redis.Redis(**redis_settings.dict())
#         self._validate_connections()

#     def _validate_connections(self):
#         try:
#             self.redis.ping()
#         except redis.RedisError:
#             self.logger.error("Redis connection failed")
#             raise

#     async def process_message(self, message: Dict[str, Any]):
#         message_id = message.get("message_id")
#         if not message_id:
#             self.logger.warning("Message missing ID")
#             return

#         redis_key = f"message:{message_id}"
#         try:
#             existing = self.redis.get(redis_key)
#         except redis.RedisError as e:
#             self.logger.error(f"Redis error: {str(e)}")
#             return

#         if existing:
#             if existing.decode() == "processed":
#                 self.logger.debug(f"Message {message_id} already processed")
#                 return
#             first_seen = float(existing.decode())
#         else:
#             first_seen = time.time()
#             try:
#                 self.redis.set(redis_key, first_seen)
#             except redis.RedisError:
#                 self.logger.error(f"Failed to store {message_id}")
#                 return

#         if time.time() - first_seen > 86400:
#             await self._handle_expired_message(message_id, redis_key)
#             return

#         try:
#             order_data = OrderSchemaIn(**message)
#             await add({"data": order_data.dict()})
#             self._mark_processed(redis_key)
#             self.logger.info(f"Processed {message_id}")

#         except ValidationError as ve:
#             await self._handle_validation_error(message_id, redis_key, ve, message)

#         except Exception as e:
#             await self._handle_processing_error(message_id, message, e)

#     async def _handle_expired_message(self, message_id: str, redis_key: str):
#         self.logger.warning(f"Message {message_id} expired")
#         try:
#             await self._send_notification(message_id)
#             self._mark_processed(redis_key)
#         except Exception as e:
#             self.logger.error(f"Expiry handling failed: {str(e)}")

#     async def _handle_validation_error(self, message_id: str, redis_key: str,
#                                      error: ValidationError, message: dict):
#         self.logger.error(f"Validation failed for {message_id}: {str(error)}")
#         try:
#             self._mark_processed(redis_key)
#             await self._send_notification(message_id)
#         except Exception as e:
#             self.logger.error(f"Validation error handling failed: {str(e)}")

#     async def _handle_processing_error(self, message_id: str, message: dict, error: Exception):
#         self.logger.error(f"Processing failed for {message_id}: {str(error)}")
#         try:
#             await self.broker.send_retry(message)
#             self.logger.info(f"Message {message_id} queued for retry")
#         except Exception as e:
#             self.logger.error(f"Retry failed for {message_id}: {str(e)}")

#     def _mark_processed(self, redis_key: str):
#         try:
#             self.redis.set(redis_key, "processed")
#         except redis.RedisError:
#             self.logger.error("Failed to mark message as processed")

#     async def _send_notification(self, message_id: str):
#         try:
#             # Реальная реализация отправки email
#             self.logger.info(f"Sent notification for {message_id}")
#         except Exception as e:
#             self.logger.error(f"Notification failed: {str(e)}")
#             raise

#     async def run_consumption(self):
#         self.logger.info("Starting message processing")
#         try:
#             async for message in self.broker.consume_messages():
#                 await self.process_message(message)
#         except Exception as e:
#             self.logger.error(f"Consumption failed: {str(e)}")
#             raise
#         finally:
#             await self.broker.stop()
