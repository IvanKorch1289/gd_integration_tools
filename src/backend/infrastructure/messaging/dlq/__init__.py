"""DLQ writers — per-transport реализации (Sprint 9 K2 W1).

Composition root выбирает writer по конфигурации.
Все реализации совместимы с :class:`DLQWriter` Protocol.

Public-API: импорт ``DLQEnvelope``/``DLQReason``/``DLQWriter`` сохранён
через re-export из :mod:`infrastructure.messaging.dlq_base` —
backwards-compat для S8 importers.

Доступные writers:

* :class:`InMemoryDLQWriter` — для unit-тестов и dev_light.
* :class:`KafkaDLQWriter` — Kafka topic dlq.{transport}.
* :class:`RabbitDLQWriter` — RabbitMQ queue dlq.{transport}.
* :class:`NATSDLQWriter` — NATS subject dlq.{transport}.
* :class:`InboxDLQWriter` — Postgres dlq_inbox table.
* :class:`FanoutDLQWriter` — публикует в несколько writers (для replay).
"""

from __future__ import annotations

from src.backend.infrastructure.messaging.dlq_base import (
    DLQEnvelope,
    DLQReason,
    DLQWriter,
)
from src.backend.infrastructure.messaging.dlq.fanout_writer import FanoutDLQWriter
from src.backend.infrastructure.messaging.dlq.inbox_writer import InboxDLQWriter
from src.backend.infrastructure.messaging.dlq.kafka_writer import KafkaDLQWriter
from src.backend.infrastructure.messaging.dlq.memory_writer import InMemoryDLQWriter
from src.backend.infrastructure.messaging.dlq.nats_writer import NATSDLQWriter
from src.backend.infrastructure.messaging.dlq.rabbit_writer import RabbitDLQWriter

__all__ = (
    "DLQEnvelope",
    "DLQReason",
    "DLQWriter",
    "FanoutDLQWriter",
    "InMemoryDLQWriter",
    "InboxDLQWriter",
    "KafkaDLQWriter",
    "NATSDLQWriter",
    "RabbitDLQWriter",
)
