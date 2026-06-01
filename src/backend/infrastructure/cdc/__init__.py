"""R2.1 — CDC backends infrastructure.

Sprint 18 W0 [wave:s18/w0-goal-driven-sweep-7-cdc-status-doc]:
обновлён статус каждого backend'а.

Backends:

* :class:`PollCDCBackend` — universal polling по `updated_at` колонке.
  **Status: production-ready**, базовый путь для PG/Oracle/MSSQL.
* :class:`ListenNotifyCDCBackend` — PostgreSQL `LISTEN/NOTIFY`. **Status:
  production-ready** для PG-only сценариев с small payload.
* :class:`DebeziumEventsCDCBackend` — Kafka topic с Debezium-сообщениями.
  **Status: scaffold** — требует поднятия Kafka+Debezium-connectора;
  методы ``consume`` / ``commit_offset`` / ``replay`` логируют намерение,
  но не подключаются к реальному Kafka. Полная реализация — Sprint R3.4.

Включение CDC в runtime: через feature-flag
``feature_flags.cdc_enabled`` (default-OFF).
"""

from src.backend.infrastructure.cdc.debezium_events_backend import (
    DebeziumEventsCDCBackend,
)
from src.backend.infrastructure.cdc.listen_notify_backend import ListenNotifyCDCBackend
from src.backend.infrastructure.cdc.poll_backend import PollCDCBackend

__all__ = ("DebeziumEventsCDCBackend", "ListenNotifyCDCBackend", "PollCDCBackend")
