"""R2.1 — CDC backends infrastructure.

Sprint 18 W0 [wave:s18/w0-goal-driven-sweep-7-cdc-status-doc]:
обновлён статус каждого backend'а.

Backends:

* :class:`PollCDCBackend` — universal polling по `updated_at` колонке.
  **Status: production-ready**, базовый путь для PG/Oracle/MSSQL.
* :class:`ListenNotifyCDCBackend` — PostgreSQL `LISTEN/NOTIFY`. **Status:
  production-ready** для PG-only сценариев с small payload.
* :class:`DebeziumEventsCDCBackend` — Kafka topic с Debezium-сообщениями.
  **Status: PRODUCTION READY (S62 W2 + S168 W2 CB)** — реальный
  ``aiokafka.AIOKafkaConsumer`` с subscribe/ack/replay loop + Circuit Breaker
  (S168 W2). Полная реализация завершена, см. ``debezium_events_backend.py``.

Включение CDC в runtime: через feature-flag
``feature_flags.cdc_enabled`` (default-OFF).
"""

from src.backend.infrastructure.cdc.debezium_events_backend import (
    DebeziumEventsCDCBackend,
)
from src.backend.infrastructure.cdc.listen_notify_backend import ListenNotifyCDCBackend
from src.backend.infrastructure.cdc.poll_backend import PollCDCBackend

__all__ = ("DebeziumEventsCDCBackend", "ListenNotifyCDCBackend", "PollCDCBackend")
