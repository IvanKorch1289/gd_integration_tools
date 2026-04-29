"""Kafka producer/consumer на базе aiokafka.

Предоставляет async API для публикации и потребления
сообщений из Apache Kafka с DSL-интеграцией.

IL2.1 (ADR-013): **DEPRECATED** — новый путь через FastStream KafkaRouter в
`src/infrastructure/clients/messaging/stream.py::StreamClient.publish_to_kafka`.
Этот прямой aiokafka-клиент остаётся shim-ом на один релиз, удаление в H3_PLUS.
Legacy call-sites, которые не переведены на FastStream — прокидывают
DeprecationWarning при импорте.

IL1.4 + IL1.5 (ADR-022):
  * Producer по умолчанию идёт с `enable_idempotence=True`, `acks="all"`,
    `max_in_flight_requests_per_connection=5` — гарантия at-least-once с
    dedup на стороне брокера.
  * Опциональный `transactional_id` для EOS-семантики (exactly-once). Если
    задан — producer становится transactional; для не-EOS операций нужен
    явный ``begin_transaction()`` / ``commit_transaction()`` / ``abort_transaction()``.
  * Circuit Breaker per-client через ``ClientCircuitBreaker`` (IL1.4):
    producer `produce()` обёрнут в `.guard()`.
"""

import logging
import os
import warnings
from abc import ABC, abstractmethod
from typing import Any

from src.core.errors import ServiceError
from src.infrastructure.resilience.client_breaker import ClientCircuitBreaker

__all__ = ("BaseKafkaClient", "KafkaClient", "get_kafka_client", "get_outbox_producer")

logger = logging.getLogger(__name__)

# IL2.1: DeprecationWarning на import.
warnings.warn(
    "`app.infrastructure.clients.messaging.kafka.KafkaClient` deprecated. "
    "Use FastStream KafkaRouter через "
    "`app.infrastructure.clients.messaging.stream.StreamClient.publish_to_kafka` "
    "(ADR-013). Этот модуль будет удалён в H3_PLUS (2026-07-01+).",
    DeprecationWarning,
    stacklevel=2,
)


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
        *,
        transactional_id: str | None = None,
        enable_idempotence: bool = True,
        circuit_breaker: "ClientCircuitBreaker | None" = None,
    ) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.group_id = group_id
        self._producer: Any = None
        self._consumer: Any = None
        # IL1.5: идемпотентный producer + (опционально) транзакционный для EOS.
        self._transactional_id = transactional_id
        self._enable_idempotence = enable_idempotence
        # IL1.4: CB на уровне клиента; при None создаётся лениво с default
        # thresholds (5 / 30s). Если клиент инстанцируется через
        # ConnectorRegistry — PoolingProfile пробросит thresholds явно.
        self._breaker = circuit_breaker or ClientCircuitBreaker(
            name="kafka",
            host=bootstrap_servers,
            failure_threshold=5,
            recovery_timeout=30.0,
        )

    async def start_producer(self) -> None:
        """Запускает Kafka producer.

        Producer-конфиг (IL1.5):
          * ``linger_ms=10``, ``batch_size=32768``, ``compression_type="snappy"``
            — высокий throughput.
          * ``enable_idempotence=True`` — дедупликация на стороне брокера.
          * ``acks="all"`` — full replication ack (требуется для idempotence).
          * ``max_in_flight_requests_per_connection=5`` — максимум для
            idempotence (при >5 aiokafka падает).
          * ``transactional_id=<...>`` — если задан, producer переходит в EOS
            (exactly-once semantics).

        При задании `transactional_id` после start() вызывается
        `init_transactions()` — обязательно для транзакционного producer'а.
        """
        from aiokafka import AIOKafkaProducer

        kwargs: dict[str, Any] = {
            "bootstrap_servers": self.bootstrap_servers,
            "linger_ms": 10,
            "batch_size": 32768,
            "compression_type": "snappy",
            "max_in_flight_requests_per_connection": 5,
        }
        if self._enable_idempotence or self._transactional_id:
            kwargs["enable_idempotence"] = True
            kwargs["acks"] = "all"
        if self._transactional_id:
            kwargs["transactional_id"] = self._transactional_id

        self._producer = AIOKafkaProducer(**kwargs)
        await self._producer.start()
        # Transactional producer требует явной инициализации транзакций.
        if self._transactional_id:
            init_tx = getattr(self._producer, "init_transactions", None)
            if callable(init_tx):
                await init_tx()
        logger.info(
            "Kafka producer запущен: bootstrap=%s, idempotence=%s, transactional=%s",
            self.bootstrap_servers,
            self._enable_idempotence or bool(self._transactional_id),
            self._transactional_id,
        )

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
            CircuitOpen: Если CB в OPEN-состоянии (IL1.4) — fast-fail без
                обращения к upstream.
        """
        if self._producer is None:
            raise ServiceError(detail="Kafka producer не запущен")

        # IL1.4: guard поверх aiokafka.send_and_wait.
        async with self._breaker.guard():
            await self._producer.send_and_wait(
                topic, value=value, key=key, headers=headers
            )
        logger.debug("Kafka: отправлено в %s", topic)

    # -- Transactional API (IL1.5) ------------------------------------
    # Используется для EOS-семантики (outbox publisher в том числе). Требует,
    # чтобы producer был инициализирован с `transactional_id`.

    async def begin_transaction(self) -> None:
        """Начать транзакцию producer'а. Требует transactional_id."""
        if self._producer is None or not self._transactional_id:
            raise ServiceError(
                detail="Transactional API доступен только с transactional_id"
            )
        await self._producer.begin_transaction()

    async def commit_transaction(self) -> None:
        if self._producer is None or not self._transactional_id:
            raise ServiceError(
                detail="Transactional API доступен только с transactional_id"
            )
        await self._producer.commit_transaction()

    async def abort_transaction(self) -> None:
        if self._producer is None or not self._transactional_id:
            raise ServiceError(
                detail="Transactional API доступен только с transactional_id"
            )
        await self._producer.abort_transaction()

    async def produce_fire_and_forget(
        self, topic: str, value: bytes, key: bytes | None = None
    ) -> None:
        """Отправляет без ожидания ACK (максимальный throughput)."""
        if self._producer is None:
            raise ServiceError(detail="Kafka producer не запущен")
        await self._producer.send(topic, value=value, key=key)

    async def produce_json(
        self, topic: str, data: dict[str, Any], key: str | None = None
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

    async def start_consumer(self, *topics: str) -> None:
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
            "Kafka consumer запущен: topics=%s, group=%s", topics, self.group_id
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

        records = await self._consumer.getmany(timeout_ms=timeout_ms, max_records=1)
        for tp_records in records.values():
            if tp_records:
                return tp_records[0]
        return None

    async def close(self) -> None:
        """Останавливает producer и consumer."""
        await self.stop_producer()
        await self.stop_consumer()


from src.core.di import app_state_singleton


@app_state_singleton("kafka_client", KafkaClient)
def get_kafka_client() -> KafkaClient:
    """Возвращает KafkaClient из app.state или lazy-init fallback.

    IL1.5: для publisher'а outbox (exactly-once) используется отдельный
    transactional KafkaClient с ``transactional_id=f"outbox-{INSTANCE_ID}"``.
    Фабрика `get_outbox_producer()` ниже возвращает такой клиент.
    """


def get_outbox_producer() -> KafkaClient:
    """Фабрика для outbox-publisher Kafka-producer'а (EOS).

    Transactional-id стабилен per-replica (INSTANCE_ID из env); это важно,
    чтобы fencing zombie-producer'ов работал правильно — см. ADR-EVT-04
    (планируется в IL2.1, одновременно с переходом на FastStream).
    """
    instance_id = os.environ.get("INSTANCE_ID", "default")
    return KafkaClient(
        transactional_id=f"outbox-{instance_id}", enable_idempotence=True
    )
