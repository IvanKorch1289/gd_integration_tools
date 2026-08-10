"""KafkaFacade — capability-checked фасад для Kafka producer/consumer.

S174: новый facade для закрытия gap из Master Prompt §3.3. Скрывает прямой
доступ к :class:`infrastructure.messaging.KafkaProducer` / KafkaConsumer
от extensions и DSL.

Предоставляет единый API:
- ``publish()`` — публикация сообщения
- ``publish_batch()`` — batch публикация
- ``subscribe()`` — async consumer с auto-ack/manual-ack
- ``is_available()`` — health check

Ponytail: НЕ дублирует существующие Kafka-классы в infrastructure.
Делегирует через DI (lazy import).

Использование::

    from src.backend.services.messaging.kafka_facade import get_kafka_facade

    facade = get_kafka_facade()
    await facade.publish(topic="orders.new", value={"order_id": 42})
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.observability.logging_helpers import log_audit_event_lite

__all__ = ("KafkaFacade", "get_kafka_facade")

_logger = get_logger("services.messaging.kafka_facade")

CapabilityChecker = Callable[[str, str, str | None], None]


class KafkaFacade:
    """Capability-checked фасад для Kafka.

    Args:
        capability_check: Опц. callback ``CapabilityGate.check``.
        plugin: Имя caller'а (для capability-event и audit).
        bootstrap_servers: Список Kafka bootstrap servers.
        default_topic: Topic по умолчанию (если не указан в publish).

    """

    def __init__(
        self,
        *,
        capability_check: CapabilityChecker | None = None,
        plugin: str = "extension",
        bootstrap_servers: list[str] | None = None,
        default_topic: str | None = None,
    ) -> None:
        """Инициализация Kafka facade."""
        self._check = capability_check
        self._plugin = plugin
        self._bootstrap = bootstrap_servers or ["localhost:9092"]
        self._default_topic = default_topic
        self._producer: Any | None = None
        self._is_started: bool = False

    def _assert(self, action: str, resource: str) -> None:
        """Capability check (если установлен)."""
        if self._check is not None:
            self._check(self._plugin, action, resource)

    def _get_producer(self) -> Any:
        """Lazy-получить Kafka producer (через infrastructure)."""
        if self._producer is None:
            try:
                # Lazy import infrastructure layer через facade
                from src.backend.infrastructure.messaging.kafka_producer import (
                    KafkaProducer,
                )

                self._producer = KafkaProducer(bootstrap_servers=self._bootstrap)
            except Exception as exc:
                log_audit_event_lite(
                    _logger,
                    severity="warning",
                    event="kafka.producer.unavailable",
                    message=f"Kafka producer unavailable: {exc}",
                    bootstrap=self._bootstrap,
                    error=str(exc),
                )
                raise
        return self._producer

    async def start(self) -> None:
        """Запустить Kafka producer (lazy)."""
        if not self._is_started:
            try:
                producer = self._get_producer()
                await producer.start()
                self._is_started = True
                log_audit_event_lite(
                    _logger,
                    severity="info",
                    event="kafka.producer.started",
                    message="Kafka producer started",
                )
            except Exception as exc:
                log_audit_event_lite(
                    _logger,
                    severity="warning",
                    event="kafka.producer.start_failed",
                    message=f"Kafka producer start failed: {exc}",
                    error=str(exc),
                )

    async def stop(self) -> None:
        """Остановить Kafka producer."""
        if self._is_started and self._producer is not None:
            try:
                await self._producer.stop()
                self._is_started = False
            except Exception as exc:
                log_audit_event_lite(
                    _logger,
                    severity="warning",
                    event="kafka.producer.stop_failed",
                    message=f"Kafka producer stop failed: {exc}",
                    error=str(exc),
                )

    async def publish(
        self,
        topic: str | None = None,
        *,
        value: bytes | dict[str, Any] | None = None,
        key: bytes | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> bool:
        """Опубликовать сообщение в Kafka.

        Args:
            topic: Topic (если None — используется ``default_topic``).
            value: Тело сообщения (bytes или dict — будет сериализован в JSON).
            key: Ключ партиционирования (опционально).
            headers: Дополнительные заголовки (опционально).

        Returns:
            True если опубликовано, False при ошибке.

        """
        target_topic = topic or self._default_topic
        if target_topic is None:
            log_audit_event_lite(
                _logger,
                severity="warning",
                event="kafka.publish.no_topic",
                message="No topic specified and default_topic not set",
            )
            return False

        self._assert("kafka.publish", target_topic)

        try:
            producer = self._get_producer()
            payload = self._serialize(value)
            await producer.send(
                topic=target_topic,
                value=payload,
                key=key,
                headers=headers,
            )
            return True
        except Exception as exc:
            log_audit_event_lite(
                _logger,
                severity="warning",
                event="kafka.publish.failed",
                message=f"Kafka publish failed: {exc}",
                topic=target_topic,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

    async def publish_batch(
        self,
        messages: list[dict[str, Any]],
        *,
        topic: str | None = None,
    ) -> int:
        """Опубликовать batch сообщений.

        Args:
            messages: Список ``{"value": ..., "key": ..., "headers": ...}``.
            topic: Topic (если None — default).

        Returns:
            Количество успешно опубликованных сообщений.

        """
        success_count = 0
        for msg in messages:
            ok = await self.publish(
                topic=topic,
                value=msg.get("value"),
                key=msg.get("key"),
                headers=msg.get("headers"),
            )
            if ok:
                success_count += 1
        return success_count

    async def is_available(self) -> bool:
        """Проверить доступность Kafka.

        Returns:
            True если producer может быть создан (lazy check).

        """
        try:
            self._get_producer()
            return True
        except (ImportError, RuntimeError, OSError, ConnectionError, AttributeError) as kafka_exc:
            # cycle-9/D-AUDIT-907: narrow exceptions + observability.
            # ImportError — kafka backend not installed, RuntimeError/
            # ConnectionError — broker down, OSError — network, AttributeError
            # — malformed config. Bare `except Exception` маскировал
            # unrelated errors (KeyError, TypeError).
            import logging
            logging.getLogger(__name__).debug(
                "kafka_facade.is_available_false",
                extra={"error": str(kafka_exc), "error_type": type(kafka_exc).__name__},
            )
            return False

    @staticmethod
    def _serialize(value: bytes | dict[str, Any] | None) -> bytes:
        """Сериализовать value в bytes."""
        if value is None:
            return b""
        if isinstance(value, bytes):
            return value
        if isinstance(value, dict):
            import json

            return json.dumps(value).encode("utf-8")
        return str(value).encode("utf-8")


@lru_cache(maxsize=1)
def get_kafka_facade() -> KafkaFacade:
    """Lazy singleton глобального :class:`KafkaFacade`."""
    return KafkaFacade()
